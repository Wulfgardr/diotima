"""Reference implementation from the Diotima v0.3-v0.5 dossier (Italian identifiers).

These modules are kept verbatim apart from path fixes, so that their deterministic test
suites keep passing while the public API is rebuilt around them:

- motore_v03: logic engine, 5-step decision procedure, audit sheet validator (35 checks)
- motore_v04: statistical engine (Beta-Binomial planning, L0 SHA-256 gate, L0-L4 reader)
- scheda_f2:  22-column audit sheet (F2 block) validator and bridge to motore_v03 (34 checks)

New code should import from the public modules (diotima.passages, diotima.mcp, ...).
"""
