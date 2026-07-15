"""
Shared constants for both GSTR-1 and GSTR-3B pipelines.
No imports required — pure data.
"""

VERSION  = "2.0"
APP_NAME = "GSTR Return Analyser"

# ── Month abbreviation lookup ────────────────────────────────────────────────
MONTH_ABBR = {
    'january': 'Jan', 'february': 'Feb', 'march': 'Mar', 'april': 'Apr',
    'may': 'May', 'june': 'Jun', 'july': 'Jul', 'august': 'Aug',
    'september': 'Sep', 'october': 'Oct', 'november': 'Nov', 'december': 'Dec',
    'jan': 'Jan', 'feb': 'Feb', 'mar': 'Mar', 'apr': 'Apr',
    'jun': 'Jun', 'jul': 'Jul', 'aug': 'Aug', 'sep': 'Sep',
    'oct': 'Oct', 'nov': 'Nov', 'dec': 'Dec',
}

# ── GSTR-1 table column names ────────────────────────────────────────────────
COL_NAMES = ['Description', 'Num_Records', 'Doc_Type', 'Value', 'IGST', 'CGST', 'SGST', 'Cess']

# ── GSTR-1 section definitions — full 33-entry list. Order matters: first match wins per row.
SECTION_DEFS = [
    ('4A',          r'4A\s*[-–]'),
    ('4B',          r'4B\s*[-–]'),
    ('5',           r'(?<![0-9A-Za-z])5\s*[-–].*B2CL'),
    ('6A',          r'6A\s*[-–]'),
    ('6B',          r'6B\s*[-–]'),
    ('6C',          r'6C\s*[-–]'),
    ('7',           r'(?<![0-9])7\s*[-–\s].*B2CS'),
    ('8',           r'(?<![0-9])8\s*[-–].*[Nn]il'),
    ('9A_B2B',      r'9A\s*[-–].*table\s*4.*B2B Regular'),
    ('9A_B2B_RCM',  r'9A\s*[-–].*table\s*4.*[Rr]everse'),
    ('9A_B2CL',     r'9A\s*[-–].*table\s*5'),
    ('9A_EXP',      r'9A\s*[-–].*table\s*6A'),
    ('9A_SEZ',      r'9A\s*[-–].*table\s*6B'),
    ('9A_DE',       r'9A\s*[-–].*table\s*6C'),
    ('9B_CDNR',     r'9B\s*[-–].*\bRegistered\b.*CDNR'),
    ('9B_CDNR_B2B', r'Credit.*?Debit.*?table\s*4.*?B2B Regular'),
    ('9B_CDNR_RCM', r'Credit.*?Debit.*?table\s*4.*?[Rr]everse'),
    ('9B_CDNR_SEZ', r'Credit.*?Debit.*?table\s*6B'),
    ('9B_CDNR_DE',  r'Credit.*?Debit.*?table\s*6C'),
    ('9C_CDNUR',    r'9B\s*[-–].*\bUnregistered\b.*CDNUR'),
    ('9C_CDNRA',    r'9C\s*[-–].*\bRegistered\b.*CDNRA'),
    ('9C_CDNURA',   r'9C\s*[-–].*\bUnregistered\b.*CDNURA'),
    ('10',          r'(?<![0-9])10\s*[-–]'),
    ('11A',         r'11A\s*\(1\)'),
    ('11B',         r'11B\s*\(1\)'),
    ('11A_AMND',    r'11A\s*[-–].*[Aa]mendment.*received'),
    ('11B_AMND',    r'11B\s*[-–].*[Aa]mendment.*adjusted'),
    ('12_HSN',      r'(?<![0-9])12\s*[-–].*HSN'),
    ('13_DOCS',     r'(?<![0-9])13\s*[-–].*[Dd]oc'),
    ('14_ECO',      r'(?<![A-Za-z0-9])14\s*[-–]'),
    ('14A_ECO',     r'(?<![A-Za-z0-9])14A\s*[-–]'),
    ('15',          r'(?<![A-Za-z0-9])15\s*[-–].*9\(5\)'),
    ('TOTAL_LIABILITY', r'Total Liability'),
]

CANONICAL_PATTERNS = {
    '4A':           r'^Total$',
    '4B':           r'^Total$',
    '5':            r'^Total$',
    '6A':           r'^Total$',
    '6B':           r'^Total$',
    '6C':           r'^Total$',
    '7':            r'^Total$',
    '8':            r'^Total$',
    '9A_B2B':       r'^Net differential',
    '9A_B2B_RCM':   r'^Net differential',
    '9A_B2CL':      r'^Net differential',
    '9A_EXP':       r'^Net differential',
    '9A_SEZ':       r'^Net differential',
    '9A_DE':        r'^Net differential',
    '9B_CDNR':      r'^Total\s*[-–]\s*Net off',
    '9B_CDNR_B2B':  r'^Net Total',
    '9B_CDNR_RCM':  r'^Net Total',
    '9B_CDNR_SEZ':  r'^Net Total',
    '9B_CDNR_DE':   r'^Net Total',
    '9C_CDNUR':     r'^Total\s*[-–]\s*Net off',
    '9C_CDNRA':     r'^Net Differential',
    '9C_CDNURA':    r'^Net Differential',
    '10':           r'^Net differential',
    '11A':          r'^Total$',
    '11B':          r'^Total$',
    '11A_AMND':     r'^Total$',
    '11B_AMND':     r'^Total$',
    '12_HSN':       r'^Total$',
    '13_DOCS':      r'^Net issued',
    '14_ECO':       r'^Total$',
    '14A_ECO':      r'^Net differential',
    '15':           r'^Total$',
    'TOTAL_LIABILITY': r'Total Liability',
}

# HSN sub-rows live inside the 12_HSN section label
HSN_SUBSECTIONS = {'12_HSN_B2B': '12_HSN', '12_HSN_B2C': '12_HSN'}

SECTION_LABELS = {
    '4A':           'B2B Regular',
    '4B':           'B2B Reverse Charge',
    '5':            'B2CL (Large – Inter-state Unregistered > ₹2.5L)',
    '6A':           'Exports (EXPWP / EXPWOP)',
    '6B':           'SEZ Supplies (SEZWP / SEZWOP)',
    '6C':           'Deemed Exports',
    '7':            'B2CS (Small – Unregistered)',
    '8':            'Nil / Exempt / Non-GST Supplies',
    '9A_B2B':       'Amendments to B2B Regular (Table 4) – Net Diff',
    '9A_B2B_RCM':   'Amendments to B2B RCM (Table 4) – Net Diff',
    '9A_B2CL':      'Amendments to B2CL (Table 5) – Net Diff',
    '9A_EXP':       'Amendments to Exports (Table 6A) – Net Diff',
    '9A_SEZ':       'Amendments to SEZ (Table 6B) – Net Diff',
    '9A_DE':        'Amendments to Deemed Exports (Table 6C) – Net Diff',
    '9B_CDNR':      'Credit/Debit Notes – Registered (CDNR) – Total Net',
    '9B_CDNR_B2B':  'CDNR – B2B Regular',
    '9B_CDNR_RCM':  'CDNR – B2B Reverse Charge',
    '9B_CDNR_SEZ':  'CDNR – SEZ (Table 6B)',
    '9B_CDNR_DE':   'CDNR – Deemed Exports (Table 6C)',
    '9C_CDNUR':     'Credit/Debit Notes – Unregistered (CDNUR)',
    '9C_CDNRA':     'Amended CDNR – Registered (CDNRA) – Net Diff',
    '9C_CDNURA':    'Amended CDNUR – Unregistered (CDNURA) – Net Diff',
    '10':           'Amendments to B2CS (Table 7) – Net Diff',
    '11A':          'Advances Received (Net of Refund Vouchers)',
    '11B':          'Advances Adjusted Against Supplies (Net)',
    '11A_AMND':     'Amendments: Advances Received',
    '11B_AMND':     'Amendments: Advances Adjusted',
    '12_HSN':       'HSN-wise Summary – Grand Total',
    '13_DOCS':      'Documents Issued',
    '14_ECO':       'E-Commerce Operator Supplies (u/s 52 & 9(5))',
    '14A_ECO':      'Amendments: E-Commerce Supplies',
    '15':           'Supplies u/s 9(5) (ECO pays tax)',
    'TOTAL_LIABILITY': 'Total Liability (excl. Reverse Charge)',
}

# Sections whose values sum to Total Liability (4B/RCM excluded per GST portal)
LIABILITY_SECTIONS = [
    '4A', '5', '6A', '6B', '6C', '7',
    '9A_B2B', '9A_B2CL', '9A_EXP', '9A_SEZ', '9A_DE',
    '9B_CDNR', '9C_CDNUR', '9C_CDNRA', '9C_CDNURA',
    '10', '11A', '11B',
    '14_ECO', '15',
]
