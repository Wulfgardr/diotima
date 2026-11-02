"""Diotima MCP server.

The host agent (Claude, Codex, ...) does the reading and reasoning with the user's own
subscription. This server provides the deterministic parts: verbatim passage lookup,
file integrity checks and sample-size planning. More tools (literature search, open-access
full text, numeric checks, the open meter) arrive in later milestones; see docs/roadmap.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from diotima import __version__
from diotima.legacy import motore_v04
from diotima.passages import find_passage as _find_passage

INSTRUCTIONS = """\
Diotima tools are deterministic checks. Rules for the agent:
- Propose, never decide: a claim counts as supported only if find_passage returns found=true
  for the verbatim quote you rely on. Otherwise report it as "not verifiable".
- Quote, do not paraphrase, when calling find_passage.
- Say whether a judgement rests on full text or only on the abstract.
- An absent judgement is never an exclusion; missing access is reported, not hidden.
"""

server = MCPServer(name="diotima", version=__version__, instructions=INSTRUCTIONS)


@server.tool()
def status() -> dict[str, Any]:
    """Report Diotima version, available tools and roadmap stage."""
    return {
        "name": "diotima",
        "version": __version__,
        "stage": "M0 (pre-alpha skeleton)",
        "tools": ["status", "find_passage", "check_file_integrity", "plan_recheck_sample"],
        "not_yet_available": [
            "literature search",
            "open-access full text retrieval",
            "numeric/CI consistency checks",
            "open evidence meter",
        ],
    }


@server.tool()
def find_passage(
    quote: str,
    source_text: str | None = None,
    source_path: str | None = None,
    context_chars: int = 160,
) -> dict[str, Any]:
    """Check that `quote` appears verbatim in a source.

    Pass the source either as `source_text` or as `source_path` (a UTF-8 text file).
    Matching tolerates only typography and whitespace, never paraphrase.
    Returns offsets, number of occurrences, surrounding context and the SHA-256 of the
    source text, so the result can be re-checked later.
    """
    if (source_text is None) == (source_path is None):
        raise ValueError("pass exactly one of source_text or source_path")
    if source_path is not None:
        source_text = Path(source_path).expanduser().read_text(encoding="utf-8")
    assert source_text is not None
    result = _find_passage(source_text, quote, context_chars=context_chars).to_dict()
    if source_path is not None:
        result["source_path"] = str(Path(source_path).expanduser().resolve())
    return result


@server.tool()
def check_file_integrity(file_path: str, expected_sha256: str, base_dir: str) -> dict[str, Any]:
    """Verify a frozen primary file against its expected SHA-256 (gate L0).

    `file_path` is resolved inside `base_dir`; paths escaping it are rejected.
    Distinguishes a missing file, an empty/unreadable file (E8) and a hash mismatch.
    """
    return motore_v04.verifica_integrita_primario_sha256(file_path, expected_sha256, base_dir=base_dir)


@server.tool()
def plan_recheck_sample(
    max_error_rate: float,
    confidence: float,
    max_errors_allowed: int,
    planned_sample: int,
) -> dict[str, Any]:
    """How many claim-passage pairs must be re-checked by hand.

    Exact Beta(1,1)-Binomial planning: with `planned_sample` pairs checked and at most
    `max_errors_allowed` errors found, is the posterior probability that the true error
    rate is below `max_error_rate` at least `confidence`? Returns the minimum N required
    and whether the plan is adequate.
    """
    r = motore_v04.plan_custom_sample_size(
        profilo="personalizzato",
        p_max=max_error_rate,
        confidenza=confidence,
        k_max_override=max_errors_allowed,
        n_custom=planned_sample,
    )
    keys = (
        "n_minimo_richiesto_per_k",
        "piano_adeguato",
        "stato_adeguatezza",
        "k_max_ammissibile_a_N",
        "regola_inerte",
        "deficit_confidenza",
    )
    return {
        "minimum_sample_for_allowed_errors": r.get("n_minimo_richiesto_per_k"),
        "plan_adequate": r.get("piano_adeguato"),
        "adequacy_state": r.get("stato_adeguatezza"),
        "max_errors_admissible_at_planned_sample": r.get("k_max_ammissibile_a_N"),
        "rule_inert": r.get("regola_inerte"),
        "confidence_deficit": r.get("deficit_confidenza"),
        "engine_output": {k: r.get(k) for k in keys},
    }


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
