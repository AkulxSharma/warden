# Two things needed from Akul

## 1. Bring the Auditor tunnel back up

The Agent's `.env` points at `WARDEN_AUDITOR_URL`, which is currently dead
(`ERR_NGROK_3200` — the tunnel is offline). Everything the Agent does right
now fails closed as a result: no real scan, no live attack test.

```bash
python3 server.py
```

```bash
ngrok http 8000
```

Send back the fresh `https://....ngrok-free.app` URL it prints. We'll drop
it into `WARDEN_AUDITOR_URL` and rerun the attack benchmark
([ATTACK_BENCH.md](ATTACK_BENCH.md)) against the real scanner, not just
fixture data.

## 2. One real scan, timed

`AUDITOR_TIMEOUT` in `transfer.py` is currently 20 seconds, picked without
any real timing data — just a guess. We want to tighten it so a dead
Auditor fails faster, but only once we know how long a real scan actually
takes.

With the tunnel from step 1 up, run one scan against a real verified
contract (not a demo address) and time it:

```bash
time curl -s "http://localhost:8000/screen?address=<a real 0x address>&chainId=11155111"
```

Send back the `real` time it prints. That's all we need — one number.
