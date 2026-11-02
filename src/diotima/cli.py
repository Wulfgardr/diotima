"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from diotima import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="diotima", description="Open, auditable evidence synthesis.")
    parser.add_argument("--version", action="version", version=f"diotima {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("mcp", help="run the MCP server on stdio")
    fp = sub.add_parser("find-passage", help="check that a quote appears verbatim in a text file")
    fp.add_argument("source", type=Path)
    fp.add_argument("quote")
    args = parser.parse_args(argv)

    if args.command == "mcp":
        from diotima.mcp.server import main as run_server

        run_server()
        return 0
    if args.command == "find-passage":
        from diotima.passages import find_passage

        result = find_passage(args.source.read_text(encoding="utf-8"), args.quote)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.found else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
