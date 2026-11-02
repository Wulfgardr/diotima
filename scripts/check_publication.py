#!/usr/bin/env python3
"""Fail if the repository contains files that must not be published.

Diotima works with copyrighted papers and with observations of commercial products.
Only identifiers, hashes, synthetic fixtures and download scripts may be committed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 512 * 1024

ALLOWED_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".csv",
    ".cfg",
    ".lock",
    ".svg",
    ".xml",
    "",
}
# images only at these exact paths (plugin icons)
IMAGE_ALLOWED = {".claude-plugin/icon.png", "assets/icon.png", "assets/social-preview.png"}
BINARY_DENY = {".pdf", ".epub", ".docx", ".doc", ".ris", ".nbib", ".enw", ".har", ".zip"}
PATH_DENY = re.compile(r"(scihub|sci-hub|libgen|uptodate|consensus_|corpus_indipendente|rea_)", re.I)
CONTENT_DENY = [
    (re.compile(r"/Users/[A-Za-z]"), "absolute personal path"),
    (re.compile(r"sci-?hub|libgen", re.I), "shadow-library reference"),
    (re.compile(r"\bsk-(ant|proj)-[A-Za-z0-9_-]{8,}"), "API key"),
]
# files allowed to mention denied words (this checker and the publishing policy)
CONTENT_EXEMPT = {"scripts/check_publication.py", "CONTRIBUTING.md"}
XML_ALLOWED_DIR = "src/diotima/legacy/data/corpus_sintetico/"


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    problems: list[str] = []
    for rel in tracked_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if rel in IMAGE_ALLOWED:
            if path.stat().st_size > MAX_BYTES:
                problems.append(f"{rel}: larger than {MAX_BYTES} bytes")
            continue
        if suffix in BINARY_DENY:
            problems.append(f"{rel}: file type {suffix} not allowed")
        elif suffix not in ALLOWED_SUFFIXES:
            problems.append(f"{rel}: file type {suffix or '(none)'} not in allow-list")
        if suffix == ".xml" and not rel.startswith(XML_ALLOWED_DIR):
            problems.append(f"{rel}: XML allowed only for synthetic fixtures")
        if PATH_DENY.search(rel):
            problems.append(f"{rel}: path matches publication deny-list")
        if path.stat().st_size > MAX_BYTES and rel != "uv.lock":
            problems.append(f"{rel}: larger than {MAX_BYTES} bytes")
        if rel in CONTENT_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel}: not UTF-8 text")
            continue
        for pattern, why in CONTENT_DENY:
            if pattern.search(text):
                problems.append(f"{rel}: contains {why}")
    if problems:
        print("Publication check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"Publication check passed ({len(tracked_files())} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
