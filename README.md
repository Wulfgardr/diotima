# Diotima

**Open, auditable evidence synthesis for Claude and Codex.**

Diotima is a plugin that turns your AI agent into a literature assistant whose answers can be checked.
Every claim it shows is tied to a verbatim passage that *code* has found in the source, with the reading
depth it rests on (full text or abstract only) and a trail anyone can re-verify.

It runs on the AI subscription you already have: your agent does the reading and reasoning, Diotima
provides the method (skills), the deterministic checks and the statistics (an MCP server).

> **Status: pre-alpha (M0).** The plugin installs and its verification tools work, but literature search,
> open-access retrieval and the open evidence meter are not built yet. See [docs/roadmap.md](docs/roadmap.md).

> **Not clinical decision support.** Diotima checks what sources say. It does not give medical advice.

## Why

AI research assistants answer quickly, but a reader cannot easily tell which claims are backed by the
full text, which rest only on an abstract, and which numbers drifted on the way. In a pilot audit of
answers from commercial tools we found a confidence interval copied wrongly, a subgroup result presented
as a general one, and a causal mechanism the sources did not state. Diotima is built to make those
errors visible.

## What it does today

| Tool / skill | What it does |
|---|---|
| `find_passage` | Checks that a quote appears verbatim in a source (tolerates only typography and whitespace) and returns offsets and the source SHA-256 |
| `check_file_integrity` | Verifies a frozen source file against its expected SHA-256 |
| `plan_recheck_sample` | Exact Beta-Binomial planning of how many claims a human must re-check |
| `diotima-method` | The rules: propose vs. verify, quote don't paraphrase, declare reading depth, absence is not evidence |
| `diotima-verify` | Verify an existing answer claim by claim |
| `diotima-search` | Answer a question from the literature (manual mode until search tools land) |

## Install

Requires [uv](https://docs.astral.sh/uv/) (the MCP server is a small Python package).

**Claude Code**

```sh
claude plugin marketplace add <owner>/diotima
claude plugin install diotima@diotima
```

Then use `/diotima:verify` or `/diotima:search`.

**Codex**

```sh
codex plugin marketplace add <owner>/diotima
codex plugin add diotima
```

**From a local clone** pass the clone path instead of `<owner>/diotima`.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
python3 scripts/check_publication.py   # nothing copyrighted or private may be committed
```

`src/diotima/legacy/` holds the reference engines from the research dossier (v0.3-v0.5, Italian
identifiers) with their original deterministic suites; new public modules are built around them.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
