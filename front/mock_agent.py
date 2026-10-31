"""Mock Agent (stand-in for workstream 2).

Same interface the real Agent should expose:
    reply(result) -> str                 iMessage-sized reply for one scan
    followup(result, question) -> str    answer from that scan's JSON only

Template only, no Claude call. Every reason comes from result["findings"].
"""
import re

from .parse import chain_name

DISCLAIMER = "Risk signal, not a guarantee. Not a full audit."
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def short(address):
    return f"{address[:6]}…{address[-4:]}"


def reply(result):
    findings = sorted(result["findings"], key=lambda f: SEVERITY_ORDER.get(f["severity"].lower(), 3))
    lines = [
        f"risk signal: {result['verdict']}",
        f"riskScore: {result['riskScore']}/100",
        f"{short(result['target'])} on {chain_name(result['chainId'])}",
    ]
    if not result["verified"]:
        lines.append("Source is unverified, so this used bytecode checks only.")
    lines.append("")
    if findings:
        lines += [f"• [{f['severity'].upper()}] {f['message']}" for f in findings]
    else:
        lines.append("• The scan flagged no issues. That does not rule out risks it does not check for.")
    lines += ["", DISCLAIMER, "Ask a follow-up, or send another address."]
    return "\n".join(lines)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def followup(result, question):
    q = _words(question)
    hits = [f for f in result["findings"]
            if q & (_words(f["id"].replace("-", " ")) - {"call", "level", "low", "only"})]
    if hits:
        body = "\n".join(f"• {f['id']}: {f['message']}" for f in hits)
        return f"From the last scan of {short(result['target'])}:\n{body}\n\n{DISCLAIMER}"
    if q & {"why", "explain", "reasons", "findings", "details", "more"}:
        return reply(result)
    return (f"The last scan of {short(result['target'])} did not flag that. "
            f"That is not proof it is absent; the scan only covers its own checks.\n\n{DISCLAIMER}")
