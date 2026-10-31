# Warden: Product and Software Development Document (Night Hack, 2026-10-30)

Status: APPROVED by Akul 2026-10-30 about 19:10 PDT. Written ~19:00 PDT. Submissions are due at 9:00 PM, so about two hours of build time remain.

## 1. Context

Warden is a Pyra-style firewall for crypto payments, rebuilt from scratch and driven over iMessage. A user texts the agent "send 0.01 to X". Before any money moves, the agent asks our Auditor whether X is risky. If the Auditor says HIGH, or fails, the agent refuses and says why. Otherwise the agent sends a Sepolia test-ETH transfer and texts the result. Pyra is used for the idea only; no Pyra code is reused, and the Kairo API it depended on is dead.

Akul owns the Auditor (workstream 1). The Agent (2) and iMessage + UI (3) are built by other teammates against the contract in section 4. Photon is handled by the iMessage teammate.

Event rules that shape the design: the demo cannot be localhost-only (it needs a public URL); judges score only work done during the sprint, so anything that existed before 4:15 PM must be disclosed (only the Pyra idea qualifies); the Photon award needs a reachable iMessage handle, not SMS-only; teams are up to four; no real money is spent, everything is Sepolia test ETH.

## 2. Product behavior

1. User texts the Warden iMessage handle: a transfer request, or just an address to screen.
2. The Agent extracts the target address, amount, and chain (default Sepolia, chainId 11155111).
3. The Agent calls the Auditor over HTTP and gets the JSON in section 4.
4. Gate, enforced in code and never by the language model: verdict HIGH, an Auditor error, or a timeout means refuse. LOW or MEDIUM means ask the user to confirm ("reply YES to send"), then send.
5. The Agent sends the Sepolia transfer from a throwaway test wallet whose key lives in `.env` only. The sender must be on an allowlist of the team's own handles.
6. The Agent texts back the outcome: sent with a tx link, refused with the reasons, or failed. Claude writes the plain-English wording but may only use findings present in the JSON. The wording never says "safe"; it says "risk signal, not a guarantee."

## 3. Auditor design (workstream 1, the part Akul owns)

Input: address (required), chainId (optional, default Sepolia), calldata and value (optional, for simulation). Output: the contract in section 4.

Flow inside `screen(address, chain_id, calldata, value)`:

1. `chain.py` fetches runtime code with `eth_getCode` over JSON-RPC (RPC URL per chain from env, with a public Sepolia default to be confirmed at build time).
2. No code means an EOA: verdict LOW, one low finding `eoa`, because contract checks do not apply.
3. Code starting with `0xef0100` and exactly 23 bytes means an EIP-7702 delegation: high finding `eip7702-delegation` naming the delegate address.
4. Otherwise try the verified-source path: `etherscan.py` calls Etherscan v2 `getsourcecode` with the `chainid` parameter and an API key from `.env`. If source exists and is a single file, write it to a temp file and run the existing `warden_scan.scan()` (reuse as is). Set `verified: true`.
5. If the source is not verified, or is a multi-file or standard-JSON bundle we cannot flatten in time, take the bytecode path and set `verified: false`. Add medium finding `unverified-source`.
6. `bytecode.py` (pure functions, no network): walk the opcodes skipping PUSH1 to PUSH32 immediate data, and flag DELEGATECALL (0xf4), SELFDESTRUCT (0xff), ORIGIN (0x32), and CALLCODE (0xf2). Read the EIP-1967 implementation, admin, and beacon slots with `eth_getStorageAt` and flag `eip1967-proxy` when set. Collect PUSH4 values and match them against an owner-only selector table (`upgradeTo`, `upgradeToAndCall`, `mint`, `pause`, `unpause`, `blacklist`, `transferOwnership`, `renounceOwnership`); selectors are computed with keccak in code and checked in tests rather than hardcoded from memory. Emit one `admin-selectors` finding that lists the names found.
7. Scoring stays as implemented in `auditor.py`: 50 per high, 15 per medium, 5 per low, capped at 100. Verdict is the worst severity; no findings is LOW, and there is no "safe" value. The thresholds are provisional.
8. Fork simulation (`fork_sim.py`) is time-boxed and optional: spawn `anvil --fork-url`, impersonate a funded test sender, replay calldata and value, and compare balances before and after. Foundry is not installed on this machine, so this needs `foundryup` and is first to be cut if time runs short. If cut, the pitch says so plainly.

Public interface: `server.py` exposes `GET /screen?address=0x..&chainId=11155111` returning the contract JSON, and `GET /health`. Every response is validated against `schema/auditor-output.schema.json` before it is returned. The server must run somewhere with a `solc` binary, so the recommended host is a small Docker service on Render or Railway rather than a serverless function; the final host is Akul's call.

Files created or changed (all in `sessions/warden/`): `chain.py`, `bytecode.py`, `etherscan.py`, `server.py`, optional `fork_sim.py`, changes to `auditor.py` (add `screen()`, keep `analyze_source()`), new tests in `tests/`, a `Dockerfile` and `requirements.txt`. Reused as is: `warden_scan.py` (`scan`, `verdict`), `schema/auditor-output.schema.json`, `fixtures/Safe.sol`, `fixtures/Vulnerable.sol`, `fixtures/auditor-output/{low,medium,high}.json`.

## 4. Contract (unchanged, fixed)

`{ target, chainId, verdict: LOW|MEDIUM|HIGH, riskScore: 0-100, verified: bool, findings: [{ id, severity: high|medium|low, message }] }`. Schema file: `schema/auditor-output.schema.json`. Mock examples for the other workstreams: `fixtures/auditor-output/`. Field names do not change without telling every workstream.

Finding ids in play: from source, `reentrancy-state-after-call`, `unprotected-state-write`, `arbitrary-send`, `tx-origin`, `unchecked-low-level-call`, `dangerous-selfdestruct`, `delegatecall`; from bytecode, `eoa`, `eip7702-delegation`, `eip1967-proxy`, `unverified-source`, `delegatecall-opcode`, `selfdestruct-opcode`, `origin-opcode`, `admin-selectors`; from simulation (if built), `sim-revert`, `sim-drains-sender`.

## 5. Build order and timing

| Window (PDT) | Work | Exit check |
|---|---|---|
| 19:00-19:20 | Approve plan. Update the workstream files and BRIEF (section 7). | Files updated, teammates pinged |
| 19:20-19:50 | `chain.py`, `bytecode.py`, EOA and 7702 handling, unit tests on synthetic bytecode | Tests pass; EOA, 7702, opcode-skip-PUSH-data cases covered |
| 19:50-20:15 | `etherscan.py` and `screen()` orchestration, verified-source path wired to `warden_scan` | Live call on a known Sepolia contract returns schema-valid JSON |
| 20:15-20:40 | `server.py`, Dockerfile, deploy to a public URL | `curl` works from a second device |
| 20:40-20:55 | Freeze. End-to-end smoke test with the Agent. Submission notes and disclosure. | Demo path works from a phone |
| only if ahead | `fork_sim.py` on anvil | Balance-diff test on a local fork |

## 6. Needed from Akul

- The `ETHERSCAN_API_KEY` in `.env` (no key means the verified-source path cannot run live).
- A hosting choice (default: Render or Railway with Docker).
- Run or approve the history squash and force-push, and the public flip. That step was denied by the auto-mode classifier earlier, so it needs Akul. The repo is still private.
- A Photon handle decision for the iMessage teammate. Photon's Beta shared line only accepts texts from the one assigned sender, so judges may be unable to text it. Options: the Stable Spectrum SDK on a Mac signed into a dedicated Apple ID (free; the Mac must stay on), a dedicated Photon line ($250 per month), or asking Photon staff at the venue. Never Akul's personal number.

## 7. Workflow-file updates (DONE 2026-10-30 ~19:15 PDT)

There are no files literally named `workflow.md`; the teammates' working files are `tasks/*.md`. Updated:

- `tasks/1-auditor.md`: add `screen()` and the HTTP interface, the bytecode finding ids, the timeline, the public-URL requirement, and the finding-id list.
- `tasks/2-agent.md`: add the transfer-agent flow, the code-enforced gate (HIGH or error or timeout means refuse), the YES confirmation, the sender allowlist, the Sepolia test wallet rules, the reply formats, and the call to `GET /screen`. Keep never-invent-findings and never-say-safe.
- `tasks/3-imessage-ui.md`: add the Photon findings (per-sender shared line, Beta polling and text-and-images limits, the three handle options), the public web view requirement, and the 9 PM deadline.
- `BRIEF-workstreams.md`: change the product description from risk-screen only to transfer agent with an Auditor gate, correct "Phantom" to Photon, mark Night Hack as confirmed, and add the timeline.
- New `PRODUCT-DEV-DOC.md` in `sessions/warden/`: this document, for sharing with the team.

I will not edit `CONTEXT-2026-10-30.md`; the orchestrator owns it.

## 8. Risks and honest limits

- A scanner like this would not have caught the Binance theft, which was an operations and key compromise. Never claim it would.
- Static detectors are shallow: six source checks plus bytecode heuristics. LOW means "nothing flagged", not "safe".
- Proxies and delegatecall are common in legitimate contracts, so those findings raise a risk signal and are not proof of a problem.
- Multi-file verified sources may fall back to the bytecode path.
- iMessage access through Photon is unofficial for local Mac setups and may be fragile.
- Fork simulation may be cut for time.

## 9. Verification

- `PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v` passes, covering source fixtures, EOA, 7702, opcode scanning that skips PUSH data, proxy slots, and selector matching.
- Every Auditor response validates against the JSON schema (the same check already run on the three fixtures).
- A live smoke test against a known Sepolia contract and a known EOA returns schema-valid JSON.
- The deployed URL answers `/health` and `/screen` from a second device.
- Gate test: a HIGH fixture and a simulated Auditor failure both produce a refusal, and a LOW fixture proceeds to confirmation.
