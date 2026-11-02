# Contributing

Thanks for helping. Before opening a pull request:

1. `uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .`
2. `python3 scripts/check_publication.py` must pass.
3. Changes that affect verification or statistics must not lower the evaluation score (see `evals/`).

## What must never be committed

- Full texts of papers that are not open access, PDFs, publisher XML, exported reference libraries.
- Material obtained from shadow libraries (Sci-Hub, LibGen and similar) or links to them.
- Screenshots, exports or reverse-engineered internals of commercial products.
- Personal data, patient data, API keys, absolute paths of your machine.

Test fixtures must be synthetic or openly licensed (state the license next to the file).

## Design rules

- The model proposes, deterministic code verifies. A new tool should return evidence a third party
  can re-check (offsets, hashes, identifiers), not just a verdict.
- Fail closed: when a check cannot be made, say "not verifiable"; never default to "supported".
