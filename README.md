# Warden

Text a crypto address, contract, or link. Get back a risk signal and the reasons.

Inspired by Pyra (NexHacks 2026, MIT). Built from scratch for Night Hack / iMessage Agent track.

## Flow

1. User texts an address, contract, or link to the Warden iMessage handle.
2. Warden resolves the address and fetches verified source (Etherscan).
3. Checks run: ENS, source validation, contract scan (Kairo, Slither fallback).
4. Reply: `risk signal: <LOW|MEDIUM|HIGH>` + reasons. Never "safe".

## Rules

- Testnet only (Sepolia) until explicitly changed.
- Output is a risk signal, not a guarantee.
- No keys in repo. Use `.env` (gitignored).

## Status

Scaffold only. Next: iMessage front, source fetch, scan gate.
