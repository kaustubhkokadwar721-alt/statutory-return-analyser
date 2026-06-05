"""Custom exceptions for the GSTR Return Analyser."""


class GSTRError(Exception):
    """Base class for all GSTR Analyser errors."""


class NoPDFsFoundError(GSTRError):
    """Raised when the input folder contains no PDF files."""


class ExcelWriteError(GSTRError):
    """Raised when an output Excel workbook cannot be written.

    Wraps the original OS/xlsxwriter exception as __cause__ so callers
    can inspect it if needed.  The message always includes a human hint
    (e.g. 'close the file in Excel first').
    """
