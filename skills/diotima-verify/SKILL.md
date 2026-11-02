---
name: diotima-verify
description: Verify the claims of an existing answer (from Consensus, UpToDate, ChatGPT, a paper or a draft) against their cited sources, claim by claim, with verbatim passages checked by code. Use when the user asks to check, audit or fact-check citations or evidence claims.
---

# Verify an answer claim by claim

Follow the rules in the `diotima-method` skill.

1. **Segment** the answer into atomic claims. Keep numbers, populations, outcomes and
   timepoints inside the claim they belong to. Number them C1, C2, ...
2. **Resolve sources** for each claim (DOI, PMID, URL or reference number in the answer).
   If a claim cites nothing, mark it `not verifiable: no source`.
3. **Obtain the source text.** Use text the user provides or open-access full text you can
   read. Record whether you have `full_text` or `abstract_only`.
   (Automatic open-access retrieval arrives in a later version.)
4. **Find the passage.** For each claim pick the sentence(s) in the source that bear on it
   and call `find_passage` with the verbatim quote and the source text or file path.
5. **Judge support.** Compare claim and passage: direction, effect size, CI, n, population,
   subgroup, timepoint, study type (protocol vs results). Assign a verdict.
6. **Report** using the report shape in `diotima-method`, then list numeric conflicts you
   noticed between sources, and the section **What is not verified**.

Never mark a claim `supports` if `find_passage` returned `found: false`.
