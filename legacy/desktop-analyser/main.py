"""GSTR Return Analyser entry point.

Run interactively:
    python main.py

Run headlessly:
    python main.py --return-type gstr1 --input-dir <pdf-folder> --output-dir <report-folder>
    python main.py --return-type gstr3b --input-dir <pdf-folder> --output-dir <report-folder>
"""

import argparse
import io
import os
import sys


if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GSTR return analysis.")
    parser.add_argument(
        "--return-type",
        choices=("gstr1", "gstr3b"),
        help="Return type to process. Omit for interactive menu.",
    )
    parser.add_argument("--input-dir", help="Folder containing source PDF files.")
    parser.add_argument("--output-dir", help="Folder where output workbooks should be written.")
    return parser.parse_args()


def _run_headless(return_type: str, input_dir: str, output_dir: str) -> int:
    if not input_dir or not output_dir:
        print("ERROR: --input-dir and --output-dir are required with --return-type.", file=sys.stderr)
        return 1
    if not os.path.isdir(input_dir):
        print(f"ERROR: Input folder not found: {input_dir}", file=sys.stderr)
        return 1

    os.makedirs(output_dir, exist_ok=True)

    try:
        if return_type == "gstr1":
            from gstr_analyser.gstr1.pipeline import run_pipeline_gstr1
            auditor_path, analytics_path = run_pipeline_gstr1(input_dir, output_dir)
        else:
            from gstr_analyser.gstr3b.pipeline import run_pipeline_gstr3b
            auditor_path, analytics_path = run_pipeline_gstr3b(input_dir, output_dir)
    except Exception as exc:
        import traceback
        print(f"ERROR: Pipeline failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    print("Done")
    print(f"Auditor:   {auditor_path} ({os.path.getsize(auditor_path) // 1024} KB)")
    print(f"Analytics: {analytics_path} ({os.path.getsize(analytics_path) // 1024} KB)")
    return 0


def main() -> int:
    args = _parse_args()
    if args.return_type:
        return _run_headless(args.return_type, args.input_dir, args.output_dir)

    from gstr_analyser.tui import run_tui

    run_tui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
