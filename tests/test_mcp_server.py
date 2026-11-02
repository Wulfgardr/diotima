import json
import os
import shutil
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

from diotima import __version__
from diotima.mcp.server import server

ROOT = Path(__file__).resolve().parents[1]


def _payload(result):
    assert not result.is_error, result
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def _call(client_target, name, args):
    async with Client(client_target) as client:
        return await client.call_tool(name, args)


def test_tools_listed_in_process():
    async def go():
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert {"status", "find_passage", "check_file_integrity", "plan_recheck_sample"} <= anyio.run(go)


def test_find_passage_tool(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text("Delirium: 10/602 vs 13/295, RR 0.38 (0.19 to 0.76).", encoding="utf-8")
    ok = _payload(
        anyio.run(_call, server, "find_passage", {"quote": "RR 0.38 (0.19 to 0.76)", "source_path": str(src)})
    )
    assert ok["found"] is True and ok["match_type"] == "exact"
    ko = _payload(
        anyio.run(_call, server, "find_passage", {"quote": "RR 0.30", "source_text": src.read_text()})
    )
    assert ko["found"] is False


def test_plan_recheck_sample_tool():
    out = _payload(
        anyio.run(
            _call,
            server,
            "plan_recheck_sample",
            {"max_error_rate": 0.04, "confidence": 0.85, "max_errors_allowed": 1, "planned_sample": 60},
        )
    )
    assert out["minimum_sample_for_allowed_errors"] == 83
    assert out["plan_adequate"] is False


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_stdio_launcher_end_to_end():
    params = StdioServerParameters(command=str(ROOT / "bin" / "diotima-mcp"), args=[], env=dict(os.environ))
    out = _payload(anyio.run(_call, params, "status", {}))
    assert out["version"] == __version__
