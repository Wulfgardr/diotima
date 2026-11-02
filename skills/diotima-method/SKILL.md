---
name: diotima-method
description: Core rules for any Diotima evidence work (searching literature, verifying claims, summarizing studies). Load before using the other diotima skills or the diotima MCP tools.
---

# Diotima method: the rules that make a synthesis auditable

Diotima splits the work: **you (the agent) read and propose; deterministic code verifies.**
A reader of the final report must be able to re-check every claim against its source.

## Non-negotiable rules

1. **Propose, never decide.** A claim is *supported* only when the verbatim quote you rely on
   has been found in the source by the `find_passage` tool. If the tool does not find it,
   the claim is *not verifiable*, whatever you believe the source says.
2. **Quote, don't paraphrase.** Pass the exact sentence(s) from the source to `find_passage`.
   Paraphrase belongs in your summary, never in the evidence.
3. **Two separate checks per claim.** (a) the passage *exists* in the source; (b) the passage
   *supports* the claim (direction, population, outcome, timepoint, subgroup). Report both.
4. **Declare reading depth.** For every source say `full_text` or `abstract_only`.
   Quantitative or methodological claims resting only on an abstract are `not verifiable`.
5. **Absence is not evidence.** A missing judgement is never an exclusion; an inaccessible
   text is reported as inaccessible, not as "no effect" or "no studies".
6. **Non-significant is not equivalent.** Never read a confidence interval that includes the
   null (1 for ratios, 0 for differences) as "no difference".
7. **Keep contradicting sources visible.** Do not drop studies that disagree with the summary.
8. **Numbers are checked, not trusted.** Effect sizes, CIs, n and timepoints in a claim must
   match the quoted passage character for character after normalization.

## Verdict vocabulary

`supports` · `partial` · `contradicts` · `insufficient` · `not verifiable`

Use `partial` when the passage supports only part of the claim (e.g. a subgroup presented as
the whole population, a different timepoint, a protocol cited as if it reported outcomes).

## Report shape

For each claim: claim text → source (DOI/PMID) → verbatim quote → `find_passage` result
(found, offsets, source SHA-256) → reading depth → verdict → one-line reason.
End with a section **What is not verified** listing every claim or source you could not check.

Diotima is not clinical decision support. Never turn a synthesis into a treatment recommendation.
