#!/usr/bin/env python3
"""Validate required Java symbols in an exported profiler text report."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--require", action="append", default=[], metavar="TEXT",
                        help="literal Java method/class text required in the report")
    parser.add_argument("--max-unknown", type=int, default=0,
                        help="maximum lines containing an unresolved-frame marker")
    args = parser.parse_args()
    if args.max_unknown < 0:
        parser.error("--max-unknown must be non-negative")
    try:
        text = args.report.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    lines = [line for line in text.splitlines() if line.strip()]
    markers = re.compile(r"(?:\[unknown\]|\bunknown(?: symbol| frame)?\b|0x[0-9a-f]{6,})",
                         re.IGNORECASE)
    unknown_lines = [line for line in lines if markers.search(line)]
    missing = [value for value in args.require if value not in text]
    result = {
        "report": str(args.report),
        "nonempty_lines": len(lines),
        "required": args.require,
        "missing_required": missing,
        "unresolved_marker_lines": len(unknown_lines),
        "status": "ok" if not missing and len(unknown_lines) <= args.max_unknown else "inconclusive",
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
