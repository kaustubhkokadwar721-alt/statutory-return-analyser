"""Browser entry point for the unified parser running under Pyodide."""


def classify_ocr_probe(text):
    """Return a JSON-safe first-page classification for staged browser OCR."""
    from document_analyser.audit import classify_document

    result = classify_document(text)
    winner = result.get("winner")
    if not winner:
        return {"accepted": False, "return_type": None, "ocr_policy": "full",
                "score": 0, "markers": []}
    return {
        "accepted": bool(result.get("accepted")),
        "return_type": winner["return_type"],
        "doc_kind": winner["doc_kind"],
        "ocr_policy": winner["handler"].ocr_policy,
        "score": winner["score"],
        "markers": winner["markers"],
    }


def run(kind, input_dir, output_dir, progress_cb=None, shard=False):
    """Run the local parser and return workbook metadata and review evidence."""
    if kind in {"bank", "bank_statement", "banking"}:
        from document_analyser.banking import run_bank_pipeline

        return run_bank_pipeline(input_dir, output_dir, progress_cb=progress_cb)

    from document_analyser.statutory_pipeline import run_unified_pipeline

    return run_unified_pipeline(
        input_dir,
        output_dir,
        progress_cb=progress_cb,
        write_workbook=not shard,
    )


def combine(shard_results, output_dir, progress_cb=None):
    """Combine extraction shards and write one globally validated workbook."""
    from document_analyser.statutory_pipeline import combine_shard_results

    return combine_shard_results(shard_results, output_dir, progress_cb=progress_cb)
