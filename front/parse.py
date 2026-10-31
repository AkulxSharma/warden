"""Parse an incoming message into a scan request.

Detects an EVM address, an optional chain (from a word like "sepolia" or an
explorer link), and whether the message was a link. No network calls.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

SEPOLIA = 11155111

ADDRESS_RE = re.compile(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
TX_HASH_RE = re.compile(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")
# Scheme, www, or a common web TLD. Bare "tx.origin" or "name.eth" is not a link.
URL_RE = re.compile(
    r"https?://\S+|www\.\S+"
    r"|\b(?:[a-z0-9-]+\.)+(?:com|io|org|net|xyz|app|co|finance|exchange|dev)\b(?:/\S*)?",
    re.I,
)
ENS_RE = re.compile(r"\b[a-z0-9-]+\.eth\b", re.I)

# Explorer hosts we can read a chain from.
EXPLORER_CHAINS = {
    "sepolia.etherscan.io": SEPOLIA,
    "etherscan.io": 1,
    "basescan.org": 8453,
    "sepolia.basescan.org": 84532,
    "arbiscan.io": 42161,
    "optimistic.etherscan.io": 10,
    "polygonscan.com": 137,
    "bscscan.com": 56,
}

# Chain words, longest first so "base sepolia" wins over "base".
CHAIN_WORDS = [
    ("base sepolia", 84532),
    ("sepolia", SEPOLIA),
    ("mainnet", 1),
    ("ethereum", 1),
    ("arbitrum", 42161),
    ("optimism", 10),
    ("polygon", 137),
    ("base", 8453),
    ("bsc", 56),
]

CHAIN_NAMES = {SEPOLIA: "Sepolia", 1: "Ethereum mainnet", 8453: "Base", 84532: "Base Sepolia",
               42161: "Arbitrum", 10: "Optimism", 137: "Polygon", 56: "BNB Chain"}

YES_WORDS = {"yes", "y", "yes send", "confirm", "send it"}
NO_WORDS = {"no", "n", "cancel", "stop", "nevermind", "never mind"}
TRANSFER_RE = re.compile(r"\b(?:send|pay|transfer)\b", re.I)
AMOUNT_RE = re.compile(r"(?<![0-9a-fx.])(\d+(?:\.\d+)?|\.\d+)\s*(?:sepolia\s*)?(?:eth|ether)?\b", re.I)

HELP_WORDS = {"help", "hi", "hello", "hey", "start", "?", "what is this", "how does this work"}


@dataclass
class Parsed:
    kind: str                      # "scan" | "transfer" | "yes" | "no" | "help" | "tx_hash" | "ens" | "link_no_address" | "text"
    address: str | None = None
    chain_id: int | None = None    # None means not stated by the user
    is_link: bool = False
    extra_addresses: list = field(default_factory=list)
    amount: float | None = None    # ETH, for "send 0.01 to 0x..."


def chain_name(chain_id):
    return CHAIN_NAMES.get(chain_id, f"chain {chain_id}")


def _chain_from_url(url):
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    host = host.removeprefix("www.")
    return EXPLORER_CHAINS.get(host)


def _chain_from_words(text):
    lower = text.lower()
    for word, chain_id in CHAIN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return chain_id
    return None


def parse(text):
    text = (text or "").strip()
    if not text:
        return Parsed("text")

    urls = [u for u in URL_RE.findall(text) if not ADDRESS_RE.fullmatch(u)]
    is_link = bool(urls)
    addresses = ADDRESS_RE.findall(text)

    if addresses:
        chain_id = None
        for url in urls:
            chain_id = _chain_from_url(url) or chain_id
        chain_id = chain_id or _chain_from_words(text)
        if TRANSFER_RE.search(text):
            rest = ADDRESS_RE.sub(" ", text)
            match = AMOUNT_RE.search(rest)
            amount = float(match.group(1)) if match else None
            return Parsed("transfer", addresses[0], chain_id, is_link, addresses[1:], amount)
        return Parsed("scan", addresses[0], chain_id, is_link, addresses[1:])

    word = text.lower().strip("!. ")
    if word in YES_WORDS:
        return Parsed("yes")
    if word in NO_WORDS:
        return Parsed("no")

    if TX_HASH_RE.search(text):
        return Parsed("tx_hash", is_link=is_link)
    if ENS_RE.search(text) and not is_link:
        return Parsed("ens")
    if is_link:
        return Parsed("link_no_address", is_link=True)
    if text.lower().strip("!. ") in HELP_WORDS:
        return Parsed("help")
    return Parsed("text")
