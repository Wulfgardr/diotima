"""Deterministic verbatim-passage lookup.

The rule Diotima enforces everywhere: a model may *propose* that a source says something,
but a claim is only shown as supported when the quoted passage is found in the source text
by this code. Matching tolerates typography (quotes, dashes, ligatures, line breaks,
whitespace) and nothing else: no paraphrase, no fuzzy similarity.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import asdict, dataclass

_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "«": '"',
        "»": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "­": "",  # soft hyphen
        "​": "",  # zero-width space
    }
)


@dataclass(frozen=True)
class PassageMatch:
    found: bool
    match_type: str  # "exact" | "normalized" | "not_found"
    start: int | None
    end: int | None
    occurrences: int
    matched_text: str | None
    source_sha256: str
    context_before: str | None
    context_after: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize text and keep, for each output char, the index of its source char."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_TYPOGRAPHY):
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            out.append(c)
            index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def normalize(text: str) -> str:
    return _normalize_with_map(text)[0]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_passage(source_text: str, quote: str, context_chars: int = 160) -> PassageMatch:
    """Find `quote` verbatim in `source_text`.

    Offsets refer to `source_text` (Python string indices). `occurrences` counts matches
    of the same kind; more than one means the quote alone does not identify a location.
    """
    if not quote or not quote.strip():
        raise ValueError("quote must be a non-empty string")
    digest = sha256_text(source_text)

    def _ctx(start: int, end: int) -> tuple[str, str]:
        return (
            source_text[max(0, start - context_chars) : start],
            source_text[end : end + context_chars],
        )

    start = source_text.find(quote)
    if start != -1:
        end = start + len(quote)
        before, after = _ctx(start, end)
        return PassageMatch(True, "exact", start, end, source_text.count(quote), quote, digest, before, after)

    norm_src, idx = _normalize_with_map(source_text)
    norm_quote = normalize(quote)
    if norm_quote:
        pos = norm_src.find(norm_quote)
        if pos != -1:
            start = idx[pos]
            end = idx[pos + len(norm_quote) - 1] + 1
            before, after = _ctx(start, end)
            return PassageMatch(
                True,
                "normalized",
                start,
                end,
                norm_src.count(norm_quote),
                source_text[start:end],
                digest,
                before,
                after,
            )

    return PassageMatch(False, "not_found", None, None, 0, None, digest, None, None)
