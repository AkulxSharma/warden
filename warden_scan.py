#!/usr/bin/env python3
"""Warden scanner: basic Solidity checks over solc's AST.

Own detectors, Slither-style. Output is a risk signal, not an audit.
Usage: python3 warden_scan.py path/to/Contract.sol [--json]
Needs `solc` on PATH (solc-select works).
"""
import json
import subprocess
import sys
from dataclasses import asdict, dataclass

EXTERNAL_CALLS = {"call", "send", "transfer", "delegatecall"}
DANGEROUS_IDS = {"selfdestruct", "suicide"}
SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class Finding:
    id: str
    severity: str
    function: str
    line: int
    message: str


def load_ast(path, solc="solc"):
    out = subprocess.run([solc, "--ast-compact-json", path], capture_output=True, text=True)
    if out.returncode != 0 or "{" not in out.stdout:
        raise RuntimeError(out.stderr.strip() or "solc failed")
    raw = out.stdout
    return json.loads(raw[raw.index("{"):])


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def offset(node):
    return int(node["src"].split(":")[0])


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def unwrap_callee(call):
    callee = call.get("expression", {})
    if callee.get("nodeType") == "FunctionCallOptions":  # call{value: x}(...)
        callee = callee.get("expression", {})
    return callee


def external_call_name(call):
    callee = unwrap_callee(call)
    if callee.get("nodeType") == "MemberAccess" and callee.get("memberName") in EXTERNAL_CALLS:
        return callee["memberName"], callee.get("expression", {})
    return None, None


def mentions_msg_sender(node):
    return any(
        n.get("nodeType") == "MemberAccess"
        and n.get("memberName") == "sender"
        and n.get("expression", {}).get("name") == "msg"
        for n in walk(node)
    )


def assigned_state_names(node, state_names):
    hits = set()
    for n in walk(node):
        if n.get("nodeType") == "Assignment":
            lhs = n.get("leftHandSide", {})
            while lhs.get("nodeType") == "IndexAccess":
                lhs = lhs.get("baseExpression", {})
            if lhs.get("nodeType") == "Identifier" and lhs.get("name") in state_names:
                hits.add(lhs["name"])
    return hits


def scan(path, solc="solc"):
    text = open(path, encoding="utf-8").read()
    tree = load_ast(path, solc)
    nodes = list(walk(tree))

    state_names = {
        n["name"] for n in nodes
        if n.get("nodeType") == "VariableDeclaration" and n.get("stateVariable")
    }
    findings = []

    for fn in (n for n in nodes if n.get("nodeType") == "FunctionDefinition"):
        if not fn.get("body"):
            continue
        name = fn.get("name") or "constructor"
        line = line_of(text, offset(fn))
        params = {p.get("name") for p in fn.get("parameters", {}).get("parameters", [])}
        body = fn["body"]
        statements = body.get("statements", [])
        visibility = fn.get("visibility", "")
        has_sender_check = mentions_msg_sender(body)

        def add(fid, sev, msg, at=line):
            findings.append(Finding(fid, sev, name, at, msg))

        # 1. Dangerous opcodes / builtins
        for n in walk(body):
            if n.get("nodeType") == "Identifier" and n.get("name") in DANGEROUS_IDS:
                add("dangerous-selfdestruct", "HIGH", f"uses {n['name']}()")
            if n.get("nodeType") == "MemberAccess" and n.get("memberName") == "delegatecall":
                add("delegatecall", "HIGH", "uses delegatecall")

        # 2. tx.origin used for auth
        for n in walk(body):
            if (n.get("nodeType") == "MemberAccess" and n.get("memberName") == "origin"
                    and n.get("expression", {}).get("name") == "tx"):
                add("tx-origin", "MEDIUM", "uses tx.origin (phishing-prone auth)")

        # 3. Ether sent to a caller-chosen address without a sender check
        for n in walk(body):
            if n.get("nodeType") != "FunctionCall":
                continue
            ext_name, receiver = external_call_name(n)
            if ext_name in ("call", "send", "transfer") and receiver is not None:
                if receiver.get("nodeType") == "Identifier" and receiver.get("name") in params and not has_sender_check:
                    add("arbitrary-send", "HIGH",
                        f"sends ETH to parameter '{receiver['name']}' with no msg.sender check",
                        line_of(text, offset(n)))

        # 4. State written after an external call (reentrancy pattern)
        call_idx = None
        for i, stmt in enumerate(statements):
            if call_idx is None and any(external_call_name(c)[0] for c in walk(stmt)
                                        if c.get("nodeType") == "FunctionCall"):
                call_idx = i
                continue
            if call_idx is not None and assigned_state_names(stmt, state_names):
                names = ", ".join(sorted(assigned_state_names(stmt, state_names)))
                add("reentrancy-state-after-call", "HIGH",
                    f"external call then state write ({names}): checks-effects-interactions broken",
                    line_of(text, offset(stmt)))
                break

        # 5. Return value of low-level call ignored
        for stmt in statements:
            if stmt.get("nodeType") == "ExpressionStatement":
                ext_name, _ = external_call_name(stmt.get("expression", {}))
                if ext_name in ("call", "delegatecall", "send"):
                    add("unchecked-low-level-call", "MEDIUM",
                        f"return value of .{ext_name}() ignored", line_of(text, offset(stmt)))

        # 6. Public/external state setter with no access control
        if visibility in ("public", "external") and not fn.get("modifiers") and not has_sender_check:
            written = assigned_state_names(body, state_names)
            if written:
                add("unprotected-state-write", "HIGH",
                    f"public function writes state ({', '.join(sorted(written))}) with no access control")

    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], f.line))
    return findings


def verdict(findings):
    if any(f.severity == "HIGH" for f in findings):
        return "HIGH"
    if any(f.severity == "MEDIUM" for f in findings):
        return "MEDIUM"
    if findings:
        return "LOW"
    return "CLEAN"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    findings = scan(path)
    result = {"file": path, "risk_signal": verdict(findings), "findings": [asdict(f) for f in findings]}
    if "--json" in argv:
        print(json.dumps(result, indent=2))
    else:
        print(f"risk signal: {result['risk_signal']} ({len(findings)} finding(s))")
        for f in findings:
            print(f"  [{f.severity}] {f.id} in {f.function} (line {f.line}): {f.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
