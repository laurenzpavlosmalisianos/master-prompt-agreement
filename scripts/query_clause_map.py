#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import safe_paths


def load_clause_map(repo_root: Path) -> dict:
    path = repo_root / "runtime" / "msa_clause_map.json"
    data = safe_paths.loads_json_no_duplicates(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("runtime/msa_clause_map.json must contain one JSON object")
    return data


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Query the machine-readable MSA clause map by disposition or operative home.",
        allow_abbrev=False,
    )
    parser.add_argument("--disposition", help="Filter by disposition such as projected or canonical-only.")
    parser.add_argument("--home", help="Filter by operative home such as runtime/operative_charter.md.")
    args = parser.parse_args()

    document = load_clause_map(repo_root)
    rows = document["clauses"]
    if args.disposition:
        rows = [row for row in rows if args.disposition in row["dispositions"]]
    if args.home:
        rows = [row for row in rows if args.home in row["operative_home"]]

    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
