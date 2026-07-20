"""Create reviewable local goldens from client PDFs; both directories are git-ignored."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web_app" / "engine"))

from document_analyser.statutory_pipeline import run_unified_pipeline


STABLE_FIELDS = (
    "ReturnType", "DocKind", "EntityID", "FY", "PeriodDate", "PrimaryAmount",
    "DocRef", "Status", "Flags", "ConfidenceGrade",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "tests" / "private_fixtures")
    parser.add_argument("--expected", type=Path, default=ROOT / "tests" / "private_expected")
    parser.add_argument("--write", action="store_true", help="write proposed JSON files after you review the terminal output")
    args = parser.parse_args()
    if not args.input.is_dir():
        raise SystemExit(f"Missing private fixture directory: {args.input}")

    with tempfile.TemporaryDirectory() as output:
        result = run_unified_pipeline(str(args.input), output)
    proposed = [{
        "SourceFile": row["SourceFile"],
        "Expected": {field: row.get(field) for field in STABLE_FIELDS},
    } for row in result["consolidated"]]
    print(json.dumps(proposed, indent=2, ensure_ascii=False))
    if not args.write:
        print("Review the proposed values, then rerun with --write to create local goldens.")
        return
    args.expected.mkdir(parents=True, exist_ok=True)
    for row in proposed:
        path = args.expected / f'{row["SourceFile"]}.json'
        path.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(proposed)} local golden file(s) to {args.expected}")


if __name__ == "__main__":
    main()
