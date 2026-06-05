"""
gstr_analyser — GSTR Return Analyser package.

Sub-packages:
    gstr1  — GSTR-1 parser, sanity checks, analytics, pipeline
    gstr3b — GSTR-3B parser, sanity checks, analytics, pipeline

Shared modules:
    constants — all lookup tables and regex patterns
    utils     — clean_cell, to_float, make_period_year, check_file_locks
    cache     — pickle-based parse-result cache
    ui        — Rich terminal progress panel + xlsxwriter Excel helpers
    cli       — command-line entry point (main menu, folder picker)
"""

VERSION  = "2.0"
APP_NAME = "GSTR Return Analyser"

__version__ = VERSION
__all__ = ["VERSION", "APP_NAME"]
