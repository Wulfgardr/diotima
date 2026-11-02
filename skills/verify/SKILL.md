---
name: verify
description: Verify the claims of an existing answer (from an AI tool, a paper or a draft) against their cited sources, claim by claim, with verbatim passages checked by code. Use when the user asks to check, audit or fact-check citations or evidence claims.
---

# Verify an answer claim by claim

Call the diotima `status` tool first and state the version in one line.

## Rules
- **Propose, never decide.** A claim is `supports` only if `find_passage` returned `found: true`
  for the verbatim quote it rests on. Otherwise it is `not verifiable`.
- **Quote, don't paraphrase** when calling `find_passage`.
- Two separate checks: the passage **exists**; the passage **supports** the claim (direction,
  effect size, CI, n, population, subgroup, timepoint, protocol vs. results).
- Declare reading depth (`full_text` / `abstract_only`); quantitative claims resting only on an
  abstract are `not verifiable`.
- A CI that includes the null (1 for ratios, 0 for differences) is never "no difference".
- Missing access is reported, never hidden; disagreeing sources stay visible.

Verdicts: `supports` · `partial` · `contradicts` · `insufficient` · `not verifiable`

## Steps
1. Segment the answer into atomic claims C1, C2, ... keeping numbers, population, outcome and
   timepoint with the claim they belong to.
2. Resolve each claim's source (DOI, PMID, URL, reference number). No source → `not verifiable: no source`.
3. Obtain the source text (provided by the user or open access) and record reading depth.
4. For each claim call `find_passage` with the verbatim sentence(s) from the source.
5. Compare claim and passage and assign a verdict with a one-line reason.
6. Report per claim: claim → source → quote → `find_passage` result (found, offsets, SHA-256)
   → reading depth → verdict → reason. Then list numeric conflicts, and end with
   **What is not verified**.

To decide how many verdicts a human should re-check, use `plan_recheck_sample` and report
whether the plan is adequate. Diotima is not clinical decision support.
