import pytest

from diotima.passages import find_passage, sha256_text

SOURCE = (
    "Results. Mortality at six months: RR 0.77 (95% CI 0.60 to 0.99; P = 0.04;\n"
    "912 participants). Transfer to hospital at one month: RR 1.32 (1.06–1.64).\n"
    "We found “no significant impact” on carer burden."
)


def test_exact_match_with_offsets():
    q = "RR 0.77 (95% CI 0.60 to 0.99"
    m = find_passage(SOURCE, q)
    assert m.found and m.match_type == "exact"
    assert SOURCE[m.start : m.end] == q
    assert m.occurrences == 1
    assert m.source_sha256 == sha256_text(SOURCE)


def test_normalized_match_tolerates_typography_and_line_breaks():
    m = find_passage(
        SOURCE, "P = 0.04; 912 participants). Transfer to hospital at one month: RR 1.32 (1.06-1.64)"
    )
    assert m.found and m.match_type == "normalized"
    assert "1.06–1.64" in m.matched_text
    m2 = find_passage(SOURCE, 'We found "no significant impact" on carer burden.')
    assert m2.found and m2.match_type == "normalized"


def test_wrong_number_is_not_found():
    # the UpToDate-style error: 0.77-0.99 instead of 0.60-0.99
    m = find_passage(SOURCE, "RR 0.77 (95% CI 0.77 to 0.99")
    assert not m.found and m.start is None


def test_paraphrase_is_not_found():
    assert not find_passage(SOURCE, "mortality was reduced at six months").found


def test_multiple_occurrences_are_counted():
    m = find_passage("a b a b", "a b")
    assert m.found and m.occurrences == 2


def test_empty_quote_rejected():
    with pytest.raises(ValueError):
        find_passage(SOURCE, "   ")
