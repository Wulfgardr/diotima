"""Plugin manifests for Claude Code and Codex must stay valid and in sync."""

import json
import tomllib
from pathlib import Path

import diotima

ROOT = Path(__file__).resolve().parents[1]


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_versions_in_sync():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert diotima.__version__ == version
    assert _json(".claude-plugin/plugin.json")["version"] == version
    assert _json(".codex-plugin/plugin.json")["version"] == version
    market = _json(".claude-plugin/marketplace.json")
    assert market["metadata"]["version"] == version
    assert market["plugins"][0]["version"] == version


def test_manifest_paths_exist():
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        m = _json(rel)
        assert (ROOT / m["skills"]).is_dir()
        assert (ROOT / m["mcpServers"]).is_file()
    assert (ROOT / _json(".claude-plugin/plugin.json")["commands"]).is_dir()
    launcher = ROOT / "bin" / "diotima-mcp"
    assert launcher.is_file() and launcher.stat().st_mode & 0o111


def test_skills_have_frontmatter():
    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    assert len(skills) >= 4
    for s in skills:
        text = s.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        head = text.split("---\n")[1]
        assert f"name: {s.parent.name}\n" in head
        assert "description: " in head
