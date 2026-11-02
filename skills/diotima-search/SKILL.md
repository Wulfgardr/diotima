---
name: diotima-search
description: Answer a research question from the scientific literature the Diotima way (protocol, transparent search, verified extracts, open evidence meter). Use when the user asks what the evidence says on a question.
---

# Search the literature and answer with verified evidence

Follow the rules in the `diotima-method` skill.

**Status: pre-alpha.** Automatic search of open scholarly databases, open-access full text
retrieval and the open evidence meter are not available yet (see `docs/roadmap.md`).
Call the `status` tool and tell the user what is and is not available.

Until then, work in **manual mode**:

1. Write a short protocol: question (PICO/PECO when it fits), inclusion and exclusion
   criteria, study types, date range. Show it to the user before searching.
2. Propose search strings for PubMed / Europe PMC / OpenAlex and show them; the user may
   correct them. Search with the tools you have and record each query and its result count.
3. Screen with an explicit criterion for each exclusion; `uncertain` is allowed.
4. For included studies, extract the key passages verbatim and verify each with
   `find_passage`; record reading depth.
5. Summarize only from verified passages; show disagreeing studies; end with
   **What is not verified**. Do not compute a pooled "consensus" percentage yet.
