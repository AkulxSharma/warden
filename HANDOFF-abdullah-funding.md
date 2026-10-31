# Prompt for Abdullah's Claude: get free Sepolia test ETH with no real wallet and no real money

Follow this step by step. Do not commit this text. Time matters: submissions are due at 9:00 PM PDT today, and the end-to-end run needs the agent wallet funded.

## The goal

The agent wallet (made with `.venv/bin/python wallet.py new-wallet`, key in `.env` as `SEPOLIA_PRIVATE_KEY`) needs about 0.05 Sepolia ETH. That covers several 0.01 ETH transfers plus fees. This is test ether with no real value. Akul does not want to use any wallet that holds real funds, and does not want to buy anything.

Hard rules:
- Never use, import, or connect a wallet that has ever held real money. A brand-new throwaway wallet with nothing in it is fine.
- Never type the agent wallet's private key into a website. Faucets only need the public address, which `wallet.py address` prints.
- Never print, log, commit, or message a private key.
- No real money is spent anywhere in this plan.

## Path A (start this first, it runs in the background): the proof-of-work faucet

Open https://sepolia-faucet.pk910.de in a browser tab. As fetched on 2026-10-30, the page says: "Just enter your ETH Address and start mining. When you've collected enough ETH, stop mining and claim your rewards." It mentions no account, no social login, no wallet connection, and no mainnet balance, so a fresh empty address should not be blocked. The fetched text was short (the page may be rendered by JavaScript), so details were not fully visible.

Do this:
1. Get the public address with `.venv/bin/python wallet.py address`.
2. Paste it into the faucet, start mining, and leave the tab open. Mining uses CPU time, so keep the laptop awake and plugged in.
3. Third-party guides disagree on amounts: one says a minimum of about 0.05 ETH is needed before you can claim, another says a fixed larger amount. Watch the page's own estimate of ETH mined per hour. If the estimate says it will take more than about 45 minutes to reach 0.05 ETH, run Path B or C in parallel.
4. When the faucet allows it, stop mining and claim. Then check with `.venv/bin/python wallet.py balance`.

## Path B (parallel): the Chainlink faucet

Open https://faucets.chain.link/sepolia. As fetched, the Ethereum Sepolia entry says "Drips 0.5 ETH" (and 25 LINK), and it asks you to connect a wallet (MetaMask, WalletConnect, or Coinbase Wallet). The fetched text did not state any mainnet-balance rule, any daily limit, or any login, but the page was partly still loading, so confirm on the page.

To use it with no real wallet: install a wallet browser extension, create a brand-new empty wallet in it, and connect that. Request the drip to that throwaway wallet, then send the ETH on to the agent wallet's address from inside the extension. Use the extension only with the new empty wallet; never import a wallet with real funds.

## Faucets that will NOT work for an empty wallet (do not waste time)

- QuickNode's Sepolia faucet states: "We do require a small mainnet balance on the wallet you are using to claim." A brand-new empty wallet fails.
- Alchemy's faucet needs a free Alchemy account, and some of its pages mention a small mainnet balance. Skip it.
- Google Cloud's faucet needs a Google sign-in and may check for a small mainnet balance. Skip it.

## Path C (fallback if no faucet pays out by about 8:15 PM PDT): a local fork with unlimited free test ETH

A local fork needs no faucet and no wallet at all. It copies Sepolia's state onto the machine, and you can set any address's balance directly.

This must run on Akul's Mac, because the live Auditor runs there and has to read the same chain. It needs Foundry, which is not installed on Akul's Mac. Installing it runs a downloaded script (`curl -L https://foundry.paradigm.xyz | bash`, then `foundryup`), so ask Akul to approve that install first. Do not install it without his yes.

After Foundry is installed:
1. Start the fork: `anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com`. Keep it running.
2. Check that the chain id is still Sepolia's, because the wallet refuses any other: `curl -s -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' http://127.0.0.1:8545` must return `0xaa36a7`. If it does not, stop and tell Akul.
3. Give the agent wallet 1 test ETH: `curl -s -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"anvil_setBalance","params":["<agent wallet address>","0xDE0B6B3A7640000"]}' http://127.0.0.1:8545`
4. Point the agent at the fork: `SEPOLIA_RPC_URL=http://127.0.0.1:8545` in the agent's `.env`.
5. Point the Auditor at the same fork: it reads `RPC_URL_11155111`. Akul sets `RPC_URL_11155111=http://127.0.0.1:8545` and restarts it.

Be honest about the trade-off: on a fork the transactions exist only on Akul's Mac, so there are no sepolia.etherscan.io links for judges, and the pitch must say the demo ran on a local fork of Sepolia. Use real Sepolia (Path A or B) whenever it works.

## After the wallet is funded

1. `.venv/bin/python wallet.py balance` must show more than 0.02 ETH before any end-to-end send.
2. Continue with the end-to-end checklist in the main prompt (Step 5), using the live Auditor URL Akul gave you.
3. Message the Conductor session with one to three lines when the wallet is funded or when you are blocked: which path worked, the balance, and what you need.

## Rules that never change

- No keys in the repo. `.env` is gitignored. Never paste a key into chat or a commit.
- Sepolia test ether only. No real money, ever.
- Never say "safe." The reply is a risk signal, not a guarantee.
- The language model never decides whether money moves. Code does.
- Every commit ends with the Co-Authored-By line from your session's current attribution reminder.
