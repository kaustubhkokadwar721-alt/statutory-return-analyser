"""Browser entry point for the unified parser running under Pyodide."""


def run(kind, input_dir, output_dir, progress_cb=None):
    """Run the local parser and return workbook metadata and review evidence."""
    from gstr_analyser.pipeline_csv import run_unified_pipeline

    return run_unified_pipeline(input_dir, output_dir, progress_cb=progress_cb)
