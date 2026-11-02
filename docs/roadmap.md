# Roadmap to v0.1.0-alpha

Goal: an open-source plugin for Claude and Codex that does what Consensus does (question → studies →
answer with evidence and an agreement indicator), but **auditable** (every claim tied to a verified
verbatim passage and its reading depth; every aggregate shown with its data, weights and assumptions),
**available** (runs on the user's own AI subscription; personal API keys optional) and **open**.

| Milestone | Scope | Exit criterion |
|---|---|---|
| **M0** Repository and plugin skeleton | package, CI, plugin manifests for Claude Code and Codex, ported dossier suites, publication check | CI green; plugin installed in both agents answers through the MCP server |
| **M1** Gold set and scorer | 120-150 labelled claim-source pairs from 3 clinical questions, dev/held-out split, `diotima eval` running the plugin headless | reproducible baseline score |
| **M2** Deterministic tools | open scholarly search (OpenAlex, PubMed, Europe PMC, Semantic Scholar, Crossref) with cache and quotas, open-access full text, numeric/CI/timepoint/subgroup checks, retractions, JSONL ledger, re-verifiable report | known error cases detected from claim + source |
| **M3** Skills, commands, subagents | screener, extractor and an independent second reader; a hook that blocks reports with unverified "supported" claims | error recall and precision ≥ 0.80 on dev |
| **M4** Statistical engine | open evidence meter (Dirichlet-multinomial, visible weights), Manski bounds for abstract-only studies, sensitivity, exploratory random-effects meta-analysis, re-check planning | published meta-analyses reproduced |
| **M5** Report and full search mode | self-contained HTML report, end-to-end `/diotima:search`, optional BYOK for headless use | third party re-verifies a report without an LLM |
| **M6** Alpha release | tested installs, eval regression gate in CI, prompt-injection tests, dogfooding, held-out score published | tag `v0.1.0-alpha` |

## Principles

- The model proposes; deterministic code verifies.
- Only open-access full text is retrieved; copyrighted texts are never committed.
- Statistics are always shown with their inputs, assumptions and sensitivity.
- Improvements are accepted only if they raise the dev score without regressions; the held-out set is
  used only at milestones.
