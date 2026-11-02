---
name: search
description: Answer a research question from the scientific literature with verified extracts and visible disagreement. Pre-alpha manual mode until search tools land. Use when the user asks what the evidence says on a question.
---

# Answer a research question with verified evidence

Call the diotima `status` tool first and tell the user, in one or two lines, the version and
which capabilities are not available yet (automatic search, open-access retrieval, evidence meter).

Follow the same rules as the `verify` skill: claims count as supported only when
`find_passage` finds the verbatim quote; declare reading depth; keep disagreeing studies visible;
never read a non-significant result as equivalence.

## Manual mode (until search tools exist)
1. Write a short protocol (question, PICO/PECO when it fits, inclusion/exclusion criteria,
   study types, dates) and show it before searching.
2. Propose search strings for PubMed / Europe PMC / OpenAlex; record each query and its count.
3. Screen with an explicit criterion for each exclusion; `uncertain` is allowed.
4. Extract key passages verbatim from included studies and verify each with `find_passage`.
5. Summarize only from verified passages, show disagreeing studies, and end with
   **What is not verified**. Do not compute a pooled agreement percentage yet.

Diotima is not clinical decision support.
