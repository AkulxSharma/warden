# Warden demo targets (Sepolia test network)

These are test contracts and wallets on the Sepolia test network. They hold test ether only, which has no real value. Text any alias below to the Warden agent, or paste the address into the Auditor, and see how it is screened. Each result is a risk signal, not a guarantee, and not a full audit.

| Alias | Address | What it is | What Warden says |
| --- | --- | --- | --- |
| `akul.eth` | [`0xE54E…563B`](https://sepolia.etherscan.io/address/0xE54Ea6a50DD6be272aEF623238E5d1DB66e9563B) | An ordinary receiving address (no contract code) | LOW, score 5 (`eoa`) |
| `andrew.eth` | [`0x01E8…9202`](https://sepolia.etherscan.io/address/0x01E86b9db57dc079B9167FDB37416dAf11a69202) | The agent's own wallet that sends the transfers | Not a target; it is the sender |
| `drainer.eth` | [`0x48F8…Bf32`](https://sepolia.etherscan.io/address/0x48F8686E6f0f4eB99a9ea89ee68C2ce93a4fBf32) | A contract whose code can self-destruct and sweep its balance | HIGH, score 65 (`selfdestruct-opcode`, `unverified-source`) |
| `vault.eth` | [`0x710a…eB2d`](https://sepolia.etherscan.io/address/0x710a4A46AcA691e8CA1388F1DCa5b4A1Ed28eB2d) | A verified vault with a reentrancy bug, an unprotected owner setter, an arbitrary-send function, and `tx.origin` auth | HIGH, score 100 (four source findings) |
| `rugpull.eth` | [`0x1c69…3B0a`](https://sepolia.etherscan.io/address/0x1c699C8347ee07F786895353632dc9B8E8CF3B0a) | A token where the owner can mint, pause, and blacklist | MEDIUM, score 30 (`admin-selectors`, `unverified-source`) |
| `proxy.eth` | [`0xb937…7CA1`](https://sepolia.etherscan.io/address/0xb9374A62D1bA2A3a0231653D47211200d6d17CA1) | An upgradeable proxy: the admin can swap the logic behind the address | MEDIUM, score 60 (`delegatecall-opcode`, `eip1967-proxy`, `admin-selectors`, `unverified-source`) |
| `phisher.eth` | [`0xCfe1…8E64`](https://sepolia.etherscan.io/address/0xCfe1752F7882C93069E8846A760122B1c0f88E64) | A wallet that authorizes with `tx.origin`, so a phishing contract can drain it | MEDIUM, score 30 (`origin-opcode`, `unverified-source`) |

How the agent treats them: a HIGH result is refused and nothing is sent (the dashboard shows it as a blocked attempt that never reached the chain). A LOW or MEDIUM result asks the sender to reply YES, then sends a real Sepolia transfer that anyone can open on Etherscan.

Source for the test contracts is in `contracts/` and `fixtures/Vulnerable.sol`. They are intentionally dangerous. Do not send them anything of value, and never reuse them on a real network.
