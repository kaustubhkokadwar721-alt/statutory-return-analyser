"""Browser entry point for the unified parser running under Pyodide."""


def run(kind, input_dir, output_dir, progress_cb=None):
    """Run the local parser and return workbook metadata and review evidence."""
    if kind in {"bank", "bank_statement", "banking"}:
        from document_analyser.banking import run_bank_pipeline

        return run_bank_pipeline(input_dir, output_dir, progress_cb=progress_cb)

    from document_analyser.statutory_pipeline import run_unified_pipeline

    return run_unified_pipeline(input_dir, output_dir, progress_cb=progress_cb)
