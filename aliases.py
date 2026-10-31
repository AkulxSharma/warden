"""Local alias book: friendly names for Sepolia test addresses. Edited only here, never by a text.

Names match exactly, ignoring case. There is no ENS lookup and no fuzzy matching.
"""
import re

ALIASES = {
    # The agent wallet, labelled as the sender in the demo story.
    "andrew.eth": "0xF86194ED621B141563a9d59F8748A47789262126",
    # Placeholder receiver: a freshly generated address nobody holds a key for.
    # Akul: replace with your own Sepolia address before the demo.
    "akul.eth": "0xE54Ea6a50DD6be272aEF623238E5d1DB66e9563B",
    # Intentionally dangerous test contract (selfdestruct), for the HIGH-risk refusal demo.
    "drainer.eth": "0x48F8686E6f0f4eB99a9ea89ee68C2ce93a4fBf32",
}

NAME = re.compile(r"(?<![\w.\-])[a-z0-9][a-z0-9\-]*\.eth(?![\w.])", re.I)


def resolve(name):
    """The 0x address for a known alias, or None."""
    return ALIASES.get(str(name).strip().lower())
