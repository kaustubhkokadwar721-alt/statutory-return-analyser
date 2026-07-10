"""Parsers for ESIC, PF, PTRC, and TDS returns.
Rewritten based on real PDF structures observed from actual samples.
"""

import re
import pandas as pd
from .utils import to_float

# ── Shared helpers ─────────────────────────────────────────────────────────────

MONTH_INDICES = {
    "APR": 1, "MAY": 2, "JUN": 3, "JUL": 4, "AUG": 5, "SEP": 6,
    "OCT": 7, "NOV": 8, "DEC": 9, "JAN": 10, "FEB": 11, "MAR": 12,
}
MONTH_NAMES = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
    "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
    "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

def _page_text(pdf) -> str:
    return "\n".join(page.extract_text() or "" for page in pdf.pages)

def _find_after(text: str, label: str, width: int = 80) -> str:
    idx = text.upper().find(label.upper())
    if idx == -1:
        return ""
    return text[idx + len(label): idx + len(label) + width].strip()

def _norm_date(s):
    """Best-effort normalise a date string to ISO (YYYY-MM-DD); return input if unparseable."""
    s = (s or "").strip()
    if not s or s.lower() == "unknown":
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y",
                "%b %d, %Y", "%b %d,%Y", "%Y-%m-%d"):
        try:
            return pd.to_datetime(s, format=fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return s

def _period_date(month_upper: str, fy_start: int):
    mi = MONTH_INDICES.get(month_upper[:3], 0)
    if mi == 0 or fy_start == 0:
        return None
    cal_m = mi + 3 if mi <= 9 else mi - 9
    cal_y = fy_start if mi <= 9 else fy_start + 1
    try:
        return pd.Timestamp(year=cal_y, month=cal_m, day=1)
    except Exception:
        return None

def _fy_from_month_year(month_upper: str, year: int):
    """Return (FY string, fy_start). April-Dec belongs to that year's FY start."""
    is_apr_dec = month_upper[:3] in ("APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC")
    fy_start = year if is_apr_dec else (year - 1 if year > 0 else 0)
    fy_str = f"{fy_start}-{str(fy_start + 1)[-2:]}" if fy_start > 0 else "Unknown"
    return fy_str, fy_start

def _row_nums(text: str, pattern: str) -> list:
    """Find first line matching pattern, return up to 6 numeric values after it."""
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return [0.0] * 6
    rest = text[m.end():].split("\n")[0]
    nums = [to_float(n) for n in re.findall(r"[\d,]+(?:\.\d+)?", rest)]
    return (nums + [0.0] * 6)[:6]


# ── TDS ────────────────────────────────────────────────────────────────────────
# PDF: "Key : Value" lines.
# Breakup: "A Tax ₹ 18,06,592" — real Unicode ₹ (U+20B9)

def parse_tds(pdf, fname: str) -> dict:
    full_text = _page_text(pdf)

    def kv(key_pattern: str) -> str:
        m = re.search(rf"{key_pattern}\s*:\s*(.+)", full_text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    # Amount with ₹ — "Amount (in Rs.) : ₹ 18,06,592"
    amt_m = re.search(
        r"Amount\s*\(in Rs\.\)\s*:\s*[\u20b9?]\s*([\d,]+(?:\.\d+)?)",
        full_text, re.IGNORECASE
    )
    total_amount_paid = to_float(amt_m.group(1)) if amt_m else 0.0

    # Breakup rows: "A Tax ₹ 18,06,592"
    def breakup(label: str) -> float:
        # Match "Letter<space>Label<space>₹<space>amount" anywhere on a line
        m = re.search(
            rf"^[A-F]\s+{re.escape(label)}\s+[\u20b9?]\s*([\d,]+(?:\.\d+)?)",
            full_text, re.IGNORECASE | re.MULTILINE
        )
        return to_float(m.group(1)) if m else 0.0

    tax       = breakup("Tax")
    surcharge = breakup("Surcharge")
    cess      = breakup("Cess")
    interest  = breakup("Interest")
    penalty   = breakup("Penalty")
    fee       = breakup("Fee under section 234E")

    tan_val        = kv(r"TAN")               or "Unknown"
    company_name   = kv(r"Name")              or "Unknown"
    fy_val         = kv(r"Financial Year")    or ""
    major_head_raw = kv(r"Major Head")        or ""
    nop_raw        = kv(r"Nature of Payment") or "Unknown"
    challan_no     = kv(r"Challan No")        or ""
    p_date_str     = kv(r"Date of Deposit")   or ""
    section_val    = nop_raw.split()[0] if nop_raw and nop_raw != "Unknown" else "Unknown"

    mh_upper = major_head_raw.upper()
    if "OTHER THAN COMPAN" in mh_upper or "0021" in mh_upper:
        major_head_val = "Other than Companies"
    elif "COMPAN" in mh_upper or "CORPORATION" in mh_upper or "0020" in mh_upper:
        major_head_val = "Corporation Tax"
    else:
        major_head_val = major_head_raw.split("(")[0].strip() or "Unknown"

    # Crosscheck: total = tax + surcharge + cess + interest + penalty + fee
    crosscheck_diff = total_amount_paid - (tax + surcharge + cess + interest + penalty + fee)

    # Payment date
    payment_date = None
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            payment_date = pd.to_datetime(p_date_str, format=fmt)
            break
        except Exception:
            pass
    if payment_date is None:
        try:
            payment_date = pd.to_datetime(p_date_str, dayfirst=True)
        except Exception:
            pass

    # TDS deduction-month logic
    deduction_date = None
    if payment_date is not None and not pd.isna(payment_date):
        p_day, p_month, p_year = payment_date.day, payment_date.month, payment_date.year
        if p_month == 4:
            deduction_date = pd.Timestamp(year=p_year, month=3, day=1)
        elif p_day <= 7 or interest > 0:
            deduction_date = (payment_date - pd.DateOffset(months=1)).replace(day=1)
        else:
            deduction_date = payment_date.replace(day=1)

    # Clamp to the stated FY. A late / additional challan (e.g. FY24-25 tax paid
    # in Jul-2025 with interest) would otherwise land the deduction month in a
    # different FY. If so, treat it as year-end (March of the FY) and flag it.
    period_estimated = False
    m_fy = re.search(r"(\d{4})", fy_val)
    fy_start = int(m_fy.group(1)) if m_fy else 0
    if deduction_date is not None and not pd.isna(deduction_date) and fy_start:
        fy_lo = pd.Timestamp(year=fy_start, month=4, day=1)
        fy_hi = pd.Timestamp(year=fy_start + 1, month=3, day=1)
        if deduction_date < fy_lo or deduction_date > fy_hi:
            deduction_date = fy_hi
            period_estimated = True

    if deduction_date is not None and not pd.isna(deduction_date):
        tds_month  = deduction_date.strftime("%B %Y")
        period_date = deduction_date
    else:
        tds_month   = "Unknown"
        period_date = None

    payment_date_str = (
        payment_date.strftime("%Y-%m-%d")
        if payment_date is not None and not pd.isna(payment_date) else None
    )

    # ── Registration / filing metadata ──
    cin_val = kv(r"CIN")             or ""
    ay_val  = kv(r"Assessment Year") or ""

    return {
        "ReturnType":             "TDS",
        "EntityID":               tan_val,
        "EntityName":             company_name,
        "FY":                     fy_val,
        "Month":                  tds_month,
        "Section":                section_val,
        "Major Head":             major_head_val,
        "Total Amount Paid":      total_amount_paid,
        "Tax":                    tax,
        "Surcharge":              surcharge,
        "Cess":                   cess,
        "Interest":               interest,
        "Penalty":                penalty,
        "Fee under section 234E": fee,
        "Crosscheck Diff":        crosscheck_diff,
        "Challan No":             challan_no,
        "Payment Date":           payment_date_str,
        "CIN":                    cin_val,
        "Assessment Year":        ay_val,
        "DocRef":                 challan_no or cin_val,
        "FilingDate":             payment_date_str,
        "PeriodDate":             period_date,
        "PeriodEstimated":        period_estimated,
    }


# ── PF ─────────────────────────────────────────────────────────────────────────
# Two observed PDF layouts:
#
# Layout A (old, 5 Challan Aug-25.pdf):
#   "Establishment Code & <ESTAB_CODE> <COMPANY NAME>... Dues for the wage month August 2025"
#   Row 1: Administration Charges
#   Row 2: Employer's Share Of  → AC01, AC02, AC10, AC21, AC22
#   Row 3: Employee's Share Of  → AC01 only
#
# Layout B (new, 6. Challan Sept-25.pdf):
#   "CHALLAN FOR WAGE MONTH : SEP 2025"
#   Table has: Code : <ESTAB_CODE> Name : <COMPANY NAME>...
#   Row 1: Employee's Share Of Contribution → AC01, NA, NA, NA, NA
#   Row 2: Employer's Share Of Contribution → AC01, NA, AC10, AC21, NA
#   Row 3: Admin/ Insp. Charges             → NA, AC02, NA, NA, AC22
#   "NA" cells should be treated as 0
#
# Both layouts use page.extract_text() reliably.

def parse_pf(pdf, fname: str) -> dict:
    full_text = _page_text(pdf)

    # ── Entity ──
    # Layout A:  "Establishment Code & <CODE> <NAME> ... Dues for the wage month"
    # Layout B / Arrears:  "Code : <CODE> Name : <NAME>"
    est_a = re.search(
        r"Establishment Code\s*&\s*(?:Name\s+)?([A-Z0-9]+)\s+(.+?)\s+Dues for the wage month",
        full_text, re.IGNORECASE | re.DOTALL,
    )
    if est_a:
        estab_code = est_a.group(1).strip()
        estab_name = re.sub(r"\s+", " ", est_a.group(2)).strip()
        estab_name = re.split(r"\bAddress\b", estab_name, flags=re.IGNORECASE)[0].strip()
    else:
        # require ≥2 leading letters so numeric "PIN Code : 411003" can't match
        code_m = re.search(r"\bCode\s*:\s*([A-Z]{2,}[A-Z0-9]+)", full_text, re.IGNORECASE)
        name_m = re.search(r"\bName\s*:\s*(.+?)(?:\n|Address)", full_text, re.IGNORECASE | re.DOTALL)
        estab_code = code_m.group(1).strip() if code_m else "Unknown"
        estab_name = re.sub(r"\s+", " ", name_m.group(1)).strip() if name_m else "Unknown"

    # ── Wage month + year (regular / dues / arrears layouts) ──
    wage_m = (
        re.search(r"CHALLAN FOR WAGE MONTH\s*:\s*([A-Za-z]+)\s+(\d{4})", full_text, re.IGNORECASE)
        or re.search(r"Dues for the wage month(?:\s+of)?\s+([A-Za-z]+)\s+(\d{4})", full_text, re.IGNORECASE)
        or re.search(r"Period\s*:\s*([A-Za-z]+)\s+(\d{4})", full_text, re.IGNORECASE)
    )
    if wage_m:
        month_val = wage_m.group(1).strip()
        raw_year  = int(wage_m.group(2))
    else:
        month_val, raw_year = "Unknown", 0

    month_upper        = month_val.upper()
    fy_str, fy_start   = _fy_from_month_year(month_upper, raw_year)

    # ── Challan / generation date ──
    challan_m = (
        re.search(r"system generated challan on\s+([^\s,\n]+)", full_text, re.IGNORECASE)
        or re.search(r"Generated On\s*(\d{2}[-/][A-Za-z0-9]+[-/]\d{4})", full_text, re.IGNORECASE)
        or re.search(r"(?:Date)[:\s]+(\d{2}[-/][A-Za-z0-9]+[-/]\d{4})", full_text, re.IGNORECASE)
    )
    challan_date = challan_m.group(1).strip() if challan_m else "Unknown"

    # ── Amounts ── ("NA" → 0). Row layout differs; discriminate by the exact label.
    clean_text = re.sub(r"\bNA\b", "0", full_text)
    has_contribution = bool(re.search(r"Share\s+Of\s+Contribution", clean_text, re.IGNORECASE))

    if has_contribution:
        # Layout B / Arrears: Employee / Employer / Admin-Insp rows
        employee_nums = _row_nums(clean_text, r"Employee.{0,5}Share\s+Of\s+Contribution")
        employer_nums = _row_nums(clean_text, r"Employer.{0,5}Share\s+Of\s+Contribution")
        admin_nums    = _row_nums(clean_text, r"Admin.{0,10}Insp\.?\s*Charges")
    else:
        # Layout A: Administration Charges / Employer's Share Of / Employee's Share Of
        admin_nums    = _row_nums(clean_text, r"Administration\s+Charges")
        employer_nums = _row_nums(clean_text, r"Employer.{0,5}Share\s+Of")
        employee_nums = _row_nums(clean_text, r"Employee.{0,5}Share\s+Of")

    employer_epf_ac01  = employer_nums[0]
    employer_eps_ac10  = employer_nums[2]
    employer_edli_ac21 = employer_nums[3]
    pf_admin_ac02      = admin_nums[1]
    edli_admin_ac22    = admin_nums[4]
    employee_epf_ac01  = employee_nums[0]

    # ── Registration / filing metadata ──
    trrn_m = re.search(r"TRRN\s*:?\s*(\d+)", full_text, re.IGNORECASE)
    trrn   = trrn_m.group(1) if trrn_m else ""

    return {
        "ReturnType":           "PF",
        "EntityID":             estab_code,
        "EntityName":           estab_name,
        "FY":                   fy_str,
        "Challan_Date":         challan_date,
        "TRRN":                 trrn,
        "DocRef":               trrn or challan_date,
        "FilingDate":           _norm_date(challan_date),
        "Employer_EPF_AC01":    employer_epf_ac01,
        "Employer_EPS_AC10":    employer_eps_ac10,
        "Employer_EDLI_AC21":   employer_edli_ac21,
        "PF_Admin_AC02":        pf_admin_ac02,
        "EDLI_Admin_AC22":      edli_admin_ac22,
        "Employee_EPF_AC01":    employee_epf_ac01,
        "PeriodDate":           _period_date(month_upper, fy_start),
        "Month":                month_val,
    }


# ── PTRC ───────────────────────────────────────────────────────────────────────
# Two observed PDF layouts:
#
# Layout A (FORM_IIIB):
#   TIN line: "PROFESSION TAX R.C. NO. (TIN) 27441462175"
#   Period:   "2025 August"  (year then month)
#   Tax:      "Total Tax Payable Rs 14,800.00"
#
# Layout B (FORM III B):
#   TIN line: "PROFESSION TAX R.C. NO. 27441462175P P ..."  (TIN has suffix P)
#   Period:   "Nov 2025"  (month abbreviation then year)
#   Tax:      "Total Tax Payable Rs. 13,600.00"

def parse_ptrc(pdf, fname: str) -> dict:
    full_text = _page_text(pdf)

    # ── TIN ──
    # Match with optional suffix (P/V) and optional trailing char
    tin_m = re.search(
        r"PROFESSION TAX R\.?C\.? NO\.?(?:\s*\(TIN\))?\s+(\d+)",
        full_text, re.IGNORECASE,
    )
    tin_val = tin_m.group(1).strip() if tin_m else "Unknown"

    # ── Company name ──
    # The PDF is two-column, so extract_text interleaves the name with the
    # right-column "Type of Return / Original". Take the block between the last
    # "Registration )" and "Periodicity", then strip the right-column noise.
    m_end = re.search(r"Periodicity", full_text, re.IGNORECASE)
    end_i = m_end.start() if m_end else len(full_text)
    regs  = [mm.end() for mm in re.finditer(r"Registration\s*\)", full_text[:end_i], re.IGNORECASE)]
    block = full_text[(regs[-1] if regs else 0):end_i]
    for pat in (r"Type of Return", r"\(?\s*Select", r"appropriate\s*\)?",
                r"\bOriginal\b", r"\bRevised\b", r"\bFresh\b", r"\bNil\b",
                r"Name of the Employer"):
        block = re.sub(pat, " ", block, flags=re.IGNORECASE)
    block = re.sub(r"\b\d+\b", " ", block)             # drop stray box numbers
    block = re.sub(r"[^A-Za-z&/.,\-() ]", " ", block)  # keep name characters only
    company_name = re.sub(r"\s+", " ", block).strip()
    company_name = re.sub(r"^M\s*/?\s*[Ss]\.?\s+", "", company_name).strip()  # drop M/s courtesy
    if not company_name:
        company_name = "Unknown"

    # ── FY ──
    fy_m = re.search(r"(\d{4})-(\d{4})", full_text)
    fy_str  = f"{fy_m.group(1)}-{fy_m.group(2)[-2:]}" if fy_m else "Unknown"
    fy_start = int(fy_m.group(1)) if fy_m else 0

    # ── Period (tax month) ──
    # Most reliable anchor: box 6 "Period Covered by Return ... 01 <Mon> <Year>".
    # (The "Period of Return" line has "( Select Appropriate )" between label and
    #  value in some versions, and filenames are unreliable, so prefer box 6.)
    period_month, period_year = "Unknown", 0
    cov = re.search(r"Period Covered by Return", full_text, re.IGNORECASE)
    if cov:
        dm = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", full_text[cov.end():cov.end() + 160])
        if dm and dm.group(2).upper()[:3] in MONTH_INDICES:
            period_month, period_year = dm.group(2), int(dm.group(3))

    # Fallbacks: "Period of Return ... 2025 August" (year first) / "... Dec 2025" (month first)
    if period_month == "Unknown":
        pr = re.search(r"Period of Return.*?(\d{4})\s+([A-Za-z]{3,9})", full_text, re.IGNORECASE)
        if pr and pr.group(2).upper()[:3] in MONTH_INDICES:
            period_year, period_month = int(pr.group(1)), pr.group(2)
    if period_month == "Unknown":
        pr = re.search(r"Period of Return.*?([A-Za-z]{3,9})\s+(\d{4})", full_text, re.IGNORECASE)
        if pr and pr.group(1).upper()[:3] in MONTH_INDICES:
            period_month, period_year = pr.group(1), int(pr.group(2))

    month_upper = period_month.upper()
    if period_year > 0:
        _, fy_start = _fy_from_month_year(month_upper, period_year)

    period_date = _period_date(month_upper, fy_start)

    # ── Tax amounts — label, then (any non-digit filler) then "Rs <amount>" ──
    def rs_val(label: str) -> float:
        m = re.search(rf"{label}.*?Rs\.?\s*([\d,]+(?:\.\d+)?)", full_text, re.IGNORECASE)
        return to_float(m.group(1)) if m else 0.0

    total_tax   = rs_val(r"Total Tax Payable")
    net_payable = rs_val(r"Net amount payable")   # may sit after "/ refundable (-)"
    # Profession-tax liability for the month is the headline figure.
    pt_paid     = total_tax if total_tax > 0 else net_payable

    # ── Registration / filing metadata ──
    mvat_m   = re.search(r"MVAT\s*/\s*GSTN TIN[^\d]*(\d{8,})", full_text, re.IGNORECASE)
    mvat_tin = mvat_m.group(1) if mvat_m else ""
    type_m   = re.search(r"Type of Return[^\n]*?\b(Original|Revised|Fresh)\b", full_text, re.IGNORECASE)
    type_of_return = type_m.group(1).title() if type_m else ""
    txn_m    = re.search(r"Transaction\s*I[dD]\s+(\d+)", full_text, re.IGNORECASE)
    doc_ref  = txn_m.group(1) if txn_m else ""
    fil_m = (re.search(r"Date of Filing Return\D*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", full_text, re.IGNORECASE)
             or re.search(r"submission of Return\s+([A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4})", full_text, re.IGNORECASE))
    filing_date = _norm_date(fil_m.group(1)) if fil_m else None

    # ── Particulars: salary-slab breakup (present only in newer FORM III B) ──
    # Each slab line ends with ... <TotalCount> <AmountOfTaxDeducted>; take the
    # last two numbers (label digits like 7500/10000 sit earlier and are ignored).
    def _slab(pat):
        m = re.search(pat + r"[^\n]*", full_text, re.IGNORECASE)
        if not m:
            return 0.0, 0.0
        vals = [to_float(n) for n in re.findall(r"[\d,]+(?:\.\d+)?", m.group(0))]
        return (vals[-2], vals[-1]) if len(vals) >= 2 else (0.0, 0.0)

    s1c, s1a = _slab(r"Do Not Exceed Rs\.?\s*7500")
    s2c, s2a = _slab(r"Exceed Rs\.?\s*7500 but <=\s*Rs\.?\s*25000")
    s3c, s3a = _slab(r"Exceed Rs\.?\s*7500 but <=\s*Rs\.?\s*10000")
    s4c, s4a = _slab(r"Exceed Rs\.?\s*10,?000 for Male")
    s5c, _   = _slab(r"Exempted U/s 27A")
    total_employees = s1c + s2c + s3c + s4c

    return {
        "ReturnType":        "PTRC",
        "EntityID":          tin_val,
        "EntityName":        company_name,
        "FY":                fy_str,
        "Period":            f"{period_month} {period_year}" if period_year else "Unknown",
        "Total Tax Payable": total_tax,
        "Net Payable":       net_payable,
        "PT Paid":           pt_paid,
        "PeriodDate":        period_date,
        "Month":             period_month,
        # registration / filing metadata
        "MVAT_TIN":          mvat_tin,
        "Type of Return":    type_of_return,
        "DocRef":            doc_ref,
        "FilingDate":        filing_date,
        # particulars breakup (salary slabs)
        "Slab_UpTo7500_Count":     s1c, "Slab_UpTo7500_Amt":     s1a,
        "Slab_7500to25000F_Count": s2c, "Slab_7500to25000F_Amt": s2a,
        "Slab_7500to10000M_Count": s3c, "Slab_7500to10000M_Amt": s3a,
        "Slab_Above10000_Count":   s4c, "Slab_Above10000_Amt":   s4a,
        "Slab_Exempt27A_Count":    s5c,
        "Total_Employees":         total_employees,
    }


# ── ESIC ───────────────────────────────────────────────────────────────────────

def parse_esic(pdf, fname: str) -> dict:
    full_text = _page_text(pdf)

    period_raw = _find_after(full_text, "Challan Period:", 20)
    period_str = period_raw.split()[0] if period_raw else ""

    if "-" in period_str:
        parts = period_str.split("-")
        month_val = parts[0]
        try:
            raw_year = int(parts[1])
            raw_year = raw_year + 2000 if raw_year < 100 else raw_year
        except ValueError:
            raw_year = 0
    else:
        month_val, raw_year = "Unknown", 0

    month_upper        = month_val.upper()
    fy_str, fy_start   = _fy_from_month_year(month_upper, raw_year)

    amt_raw     = _find_after(full_text, "Amount Paid:", 20)
    amount_paid = to_float(amt_raw.split()[0]) if amt_raw else 0.0

    challan_raw = _find_after(full_text, "Challan Number", 30).replace(":", "").strip()
    challan_num = challan_raw.split()[0] if challan_raw else "Unknown"

    date_raw = _find_after(full_text, "Challan Submitted Date", 30)
    date_str = date_raw.split()[0] if date_raw else "Unknown"

    return {
        "ReturnType":    "ESIC",
        "EntityID":      "",
        "EntityName":    "",
        "FY":            fy_str,
        "Amount":        amount_paid,
        "ChallanNumber": challan_num,
        "ChallanDate":   date_str,
        "DocRef":        challan_num,
        "FilingDate":    _norm_date(date_str),
        "PeriodDate":    _period_date(month_upper, fy_start),
        "Month":         month_val,
    }
