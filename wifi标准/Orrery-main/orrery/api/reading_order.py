"""The order a reader should meet the corpus in — one list, two consumers.

The console's protocol list and the vocabulary page's protocol panel share this
order so a reader never has to learn two. Entries are directory prefixes matched
against corpus-relative paths; anything not named still appears, after the named
ones. This module imports nothing, so neither consumer pulls in the other's
dependencies.
"""

from __future__ import annotations

#: The protocols this corpus leads with, in the order a reader should meet them
#: — the textbook ones first, in teaching order, then the standards. Everything
#: not named here still appears, ordered by size, after these.
HEADLINE = (
    "academic/NSPK",
    "academic/Denning-Sacco",
    "academic/Otway-Rees",
    "academic/NSSK",
    "academic/Neuman-Stubblebine",
    "academic/Kao-Chow",
    "academic/Yahalom",
    "rfc/EDHOC",
    # Entity authentication, ahead of the key exchanges that assume it.
    "ISO/9798",
    "rfc/IKEV2",
    "3gpp/5G-AKA",
    "rfc/OAuth-2.0",
    "rfc/TLS13",
    "informal/Bluetooth",
    "informal/FIDO",
    # Eighty-odd mechanisms across two parts; worth attempting last.
    "ISO/11770",
)


def headline_rank(rel: str) -> int:
    """Where a corpus-relative directory sits among the headline prefixes;
    unnamed directories land after every named one.

    A prefix, so a protocol with several drafts takes one position. Both
    separators count: variants are subdirectories (``rfc/EDHOC/draft-08``) while
    a standard's parts sit in the directory name (``ISO/9798-2-...``).
    """
    return next((i for i, pre in enumerate(HEADLINE)
                 if rel == pre or rel.startswith(pre + "/")
                 or rel.startswith(pre + "-")),
                len(HEADLINE))


def name_rank(rel: str) -> tuple[int, str]:
    """The panel's sort key: headline position, then the path itself, so the
    unnamed tail comes out alphabetical."""
    return (headline_rank(rel), rel)
