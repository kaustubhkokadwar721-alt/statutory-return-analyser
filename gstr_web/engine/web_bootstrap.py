"""Browser bootstrap for the GSTR engine running under Pyodide.

The desktop pipelines parse PDFs in a ThreadPoolExecutor. Pyodide's WASM
runtime has no OS threads, so we swap the executor for a synchronous one.
Output is byte-for-byte identical — threading was only a speed optimisation.
"""

import os
import glob


class _SerialFuture:
    __slots__ = ("_result", "_exc")

    def __init__(self, fn, args, kwargs):
        self._exc = None
        self._result = None
        try:
            self._result = fn(*args, **kwargs)
        except BaseException as e:  # mirror Future semantics: capture, re-raise on result()
            self._exc = e

    def result(self, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._result


class _SerialExecutor:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args, **kwargs):
        return _SerialFuture(fn, args, kwargs)

    def shutdown(self, *a, **k):
        pass


def _as_completed(fs, timeout=None):
    # fs is the {future: filepath} dict (or any iterable of futures).
    return list(fs)


def _patch_serial():
    from gstr_analyser.gstr1 import pipeline as p1
    from gstr_analyser.gstr3b import pipeline as p3
    for mod in (p1, p3):
        mod.ThreadPoolExecutor = _SerialExecutor
        mod.as_completed = _as_completed


def run(kind, input_dir, output_dir, progress_cb=None):
    """Run the unified compliance return CSV pipeline.

    Returns a list of dicts describing the output CSV files.
    """
    _patch_serial()
    from gstr_analyser.pipeline_csv import run_unified_pipeline
    return run_unified_pipeline(input_dir, output_dir, progress_cb=progress_cb)


def list_pdfs(input_dir):
    return sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
