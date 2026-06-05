"""
Pickle-based parse-result cache.

Purpose: skip re-parsing unchanged PDFs on repeat runs.
Cache key = filename + file_size + mtime_nanoseconds → unique per file version.
Cache file = {output_dir}/.parse_cache.pkl  (hidden file, per output folder).

Usage:
    cache = _load_cache(cache_file)
    ...
    result = cache.get(key) or parse_pdf(path)
    cache[key] = result
    _save_cache(cache_file, cache)

Bump _CACHE_VERSION whenever the parse output schema changes — invalidates old caches.
"""

import os
import pickle

_CACHE_VERSION = 3  # bumped: GSTR-3B Table_4_ITC column _section → Section


def _cache_key(pdf_path: str) -> str:
    """Stable string key: filename + size + mtime (nanoseconds).

    Falls back to 'filename|0|0' if the file disappears or is unreadable
    between the directory glob and the parse call — guarantees a cache miss
    rather than an unhandled OSError.
    """
    try:
        s = os.stat(pdf_path)
        return f"{os.path.basename(pdf_path)}|{s.st_size}|{s.st_mtime_ns}"
    except OSError:
        return f"{os.path.basename(pdf_path)}|0|0"


def _load_cache(cache_file: str) -> dict:
    """Load cache from disk. Returns empty dict on miss, corruption, or version mismatch."""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            if isinstance(data, dict) and data.get('_v') == _CACHE_VERSION:
                return data
    except Exception:
        pass
    return {'_v': _CACHE_VERSION}


def _save_cache(cache_file: str, cache: dict) -> None:
    """Persist cache to disk. Warns to stderr on write failure (non-critical)."""
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(cache, f, protocol=4)
    except Exception as exc:
        import sys
        print(f"[cache] Warning: could not save parse cache: {exc}", file=sys.stderr)


def _copy_result(r: dict | None) -> dict | None:
    """
    Return a shallow copy of a parse result dict so cached DataFrames aren't
    mutated when the caller injects context columns (GSTIN, Period_Year, etc.).
    """
    if r is None:
        return None
    import pandas as pd
    out = {}
    for k, v in r.items():
        if isinstance(v, pd.DataFrame):
            out[k] = v.copy()
        elif isinstance(v, dict):
            out[k] = dict(v)
        else:
            out[k] = v
    return out
