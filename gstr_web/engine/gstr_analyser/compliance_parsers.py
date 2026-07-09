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
        "PeriodDate":             period_date,
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

    # ── Detect layout ──
    is_layout_b = bool(re.search(r"CHALLAN FOR WAGE MONTH", full_text, re.IGNORECASE))

    # ── Entity: Layout A ──
    if not is_layout_b:
        est_m = re.search(
            r"Establishment Code\s*&\s*(?:Name\s+)?([A-Z0-9]+)\s+(.+?)\s+Dues for the wage month",
            full_text, re.IGNORECASE | re.DOTALL,
        )
        if est_m:
            estab_code = est_m.group(1).strip()
            estab_name = re.sub(r"\s+", " ", est_m.group(2)).strip()
            estab_name = re.split(r"\bAddress\b", estab_name, flags=re.IGNORECASE)[0].strip()
        else:
            estab_code, estab_name = "Unknown", "Unknown"

        wage_m = re.search(
            r"Dues for the wage month(?:\s+of)?\s+([A-Za-z]+)\s+(\d{4})",
            full_text, re.IGNORECASE,
        )

    # ── Entity: Layout B ──
    else:
        # "Code : <ESTAB_CODE> Name : <COMPANY NAME>..."
        code_m = re.search(r"Code\s*:\s*([A-Z0-9]+)", full_text, re.IGNORECASE)
        name_m = re.search(r"Name\s*:\s*(.+?)(?:\n|Address)", full_text, re.IGNORECASE | re.DOTALL)
        estab_code = code_m.group(1).strip() if code_m else "Unknown"
        estab_name = re.sub(r"\s+", " ", name_m.group(1)).strip() if name_m else "Unknown"

        # "CHALLAN FOR WAGE MONTH : SEP 2025"
        wage_m = re.search(
            r"CHALLAN FOR WAGE MONTH\s*:\s*([A-Za-z]+)\s+(\d{4})",
            full_text, re.IGNORECASE,
        )

    if wage_m:
        month_val = wage_m.group(1).strip()
        raw_year  = int(wage_m.group(2))
    else:
        month_val, raw_year = "Unknown", 0

    month_upper        = month_val.upper()
    fy_str, fy_start   = _fy_from_month_year(month_upper, raw_year)

    # ── Challan date ──
    challan_m = re.search(r"system generated challan on\s+([^\s,\n]+)", full_text, re.IGNORECASE)
    if not challan_m:
        challan_m = re.search(r"(?:Date|Generated On)[:\s]+(\d{2}[-/][A-Za-z0-9]+[-/]\d{4})", full_text, re.IGNORECASE)
    challan_date = challan_m.group(1).strip() if challan_m else "Unknown"

    # ── Amounts ──
    # Treat "NA" as 0: replace NA tokens before parsing
    clean_text = re.sub(r"\bNA\b", "0", full_text)

    if not is_layout_b:
        # Layout A: columns are AC01 AC02 AC10 AC21 AC22 TOTAL
        admin_nums    = _row_nums(clean_text, r"Administration\s+Charges")
        employer_nums = _row_nums(clean_text, r"Employer.{0,5}Share\s+Of")
        employee_nums = _row_nums(clean_text, r"Employee.{0,5}Share\s+Of")
        employer_epf_ac01  = employer_nums[0]
        employer_eps_ac10  = employer_nums[2]
        employer_edli_ac21 = employer_nums[3]
        pf_admin_ac02      = admin_nums[1]
        edli_admin_ac22    = admin_nums[4]
        employee_epf_ac01  = employee_nums[0]
    else:
        # Layout B: Employee row first, Employer row second, Admin row third
        # Employee row: AC01  (employee EPF share)
        # Employer row: AC01(employer EPF), _, AC10(EPS), AC21(EDLI), _
        # Admin row:   _, AC02(PF admin), _, _, AC22(EDLI admin)
        employee_nums = _row_nums(clean_text, r"Employee.{0,5}Share\s+Of\s+Contribution")
        employer_nums = _row_nums(clean_text, r"Employer.{0,5}Share\s+Of\s+Contribution")
        admin_nums    = _row_nums(clean_text, r"Admin.{0,10}Insp\.?\s*Charges")
        employer_epf_ac01  = employer_nums[0]
        employer_eps_ac10  = employer_nums[2]
        employer_edli_ac21 = employer_nums[3]
        pf_admin_ac02      = admin_nums[1]
        edli_admin_ac22    = admin_nums[4]
        employee_epf_ac01  = employee_nums[0]

    return {
        "ReturnType":           "PF",
        "EntityID":             estab_code,
        "EntityName":           estab_name,
        "FY":                   fy_str,
        "Challan_Date":         challan_date,
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
    name_m = re.search(
        r"Name of the Employer\s+(.+?)(?:\s+Type of Return|\s+Periodicity|\n)",
        full_text, re.IGNORECASE | re.DOTALL,
    )
    if name_m:
        company_name = re.sub(r"\s+", " ", name_m.group(1)).strip()
        # Clean prefix artefacts
        company_name = re.sub(r"^M/?s\.?\s+", "", company_name).strip()
    else:
        company_name = "Unknown"

    # ── FY ──
    fy_m = re.search(r"(\d{4})-(\d{4})", full_text)
    fy_str  = f"{fy_m.group(1)}-{fy_m.group(2)[-2:]}" if fy_m else "Unknown"
    fy_start = int(fy_m.group(1)) if fy_m else 0

    # ── Period month + year ──
    # Layout A: "Period of Return 2025 August"  (year first)
    period_m_a = re.search(
        r"Period of Return[^0-9a-zA-Z]*(\d{4})\s+([A-Za-z]+)",
        full_text, re.IGNORECASE,
    )
    # Layout B: "Period of Return( ...) Nov 2025"  (month first)
    period_m_b = re.search(
        r"Period of Return[^0-9a-zA-Z]*([A-Za-z]{3,9})\s+(\d{4})",
        full_text, re.IGNORECASE,
    )

    period_month, period_year = "Unknown", 0

    if period_m_a:
        candidate_month = period_m_a.group(2).strip()
        # Confirm it looks like a real month (not "appropriate" or junk)
        if candidate_month.upper()[:3] in MONTH_INDICES:
            period_year  = int(period_m_a.group(1))
            period_month = candidate_month
    
    if period_month == "Unknown" and period_m_b:
        candidate_month = period_m_b.group(1).strip()
        if candidate_month.upper()[:3] in MONTH_INDICES:
            period_month = candidate_month
            period_year  = int(period_m_b.group(2))

    # Last fallback: "From 01 Nov 2025"
    if period_month == "Unknown":
        from_m = re.search(r"From\s+\d+\s+([A-Za-z]+)\s+(\d{4})", full_text, re.IGNORECASE)
        if from_m and from_m.group(1).upper()[:3] in MONTH_INDICES:
            period_month = from_m.group(1).strip()
            period_year  = int(from_m.group(2))

    month_upper = period_month.upper()
    # Recalculate fy_start from period year if available
    if period_year > 0:
        _, fy_start = _fy_from_month_year(month_upper, period_year)

    period_date = _period_date(month_upper, fy_start)

    # ── Tax amounts — "Rs." or "Rs" followed by amount ──
    def rs_val(pattern: str) -> float:
        m = re.search(rf"{pattern}\s+Rs\.?\s*([\d,]+(?:\.\d+)?)", full_text, re.IGNORECASE)
        return to_float(m.group(1)) if m else 0.0

    total_tax   = rs_val(r"Total Tax Payable")
    net_payable = rs_val(r"Net amount payable")
    pt_paid     = net_payable if net_payable > 0 else total_tax

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
        "PeriodDate":    _period_date(month_upper, fy_start),
        "Month":         month_val,
    }
