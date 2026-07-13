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

def _to_month_year(s: str):
    """Parse 'JUL-2025' / 'JUL 2025' / 'July 2025' → ('JUL', 2025); else ('Unknown', 0)."""
    m = re.search(r"([A-Za-z]{3,9})[-\s]+(\d{4})", s or "")
    if not m:
        return "Unknown", 0
    mon = m.group(1).upper()[:3]
    if mon not in MONTH_INDICES:
        return "Unknown", 0
    return mon, int(m.group(2))

def _fy_from_date(dt):
    """Return (FY string, fy_start) for a pandas Timestamp on the Apr–Mar Indian FY."""
    if dt is None:
        return "Unknown", 0
    try:
        y, mth = dt.year, dt.month
    except Exception:
        return "Unknown", 0
    fy_start = y if mth >= 4 else y - 1
    return f"{fy_start}-{str(fy_start + 1)[-2:]}", fy_start

def _strip_ms(name: str) -> str:
    """Drop the "M/s" / "M S" courtesy prefix Maharashtra forms print before a dealer name."""
    return re.sub(r"^M\s*/?\s*[Ss]\.?\s+", "", (name or "")).strip()

def _parse_date(s: str):
    """Best-effort parse of dd-mm-yyyy / dd/mm/yyyy / dd-Mon-yyyy → Timestamp or None."""
    s = (s or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d/%b/%Y", "%d %b %Y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except Exception:
            pass
    try:
        return pd.to_datetime(s, dayfirst=True)
    except Exception:
        return None


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

    # ── Grand total (the full remittance — used for reconciliation) ──
    grand_total = 0.0
    gt_m = re.search(r"Grand Total\s*:([^\n]*)", full_text, re.IGNORECASE)
    if gt_m:
        gt_nums = re.findall(r"[\d,]+(?:\.\d+)?", gt_m.group(1))
        if gt_nums:
            grand_total = to_float(gt_nums[-1])
    if grand_total <= 0:
        grand_total = (employer_epf_ac01 + employer_eps_ac10 + employer_edli_ac21
                       + pf_admin_ac02 + edli_admin_ac22 + employee_epf_ac01)

    # ── Registration / filing metadata ──
    trrn_m = re.search(r"TRRN\s*:?\s*(\d+)", full_text, re.IGNORECASE)
    trrn   = trrn_m.group(1) if trrn_m else ""

    return {
        "ReturnType":           "PF",
        "DocKind":              "Challan",
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
        "Grand_Total":          grand_total,
        "PrimaryAmount":        grand_total,
        "PeriodDate":           _period_date(month_upper, fy_start),
        "Month":                month_val,
    }


# ── PF: ECR (Electronic Challan cum Return) — the member-wise return ──────────────
# Headline totals live on page 1 in "Label  Value" (space-separated) form.

def _pf_totals(text: str):
    """Extract the three EPFO contribution totals shared by ECR & Arrears docs."""
    def grab(label):
        m = re.search(rf"{label}\s+([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
        return to_float(m.group(1)) if m else 0.0
    epf     = grab(r"Total EPF Contribution")
    eps     = grab(r"Total EPS Contribution")
    epf_eps = grab(r"Total EPF-EPS Contribution")
    return epf, eps, epf_eps


def _pf_entity(text: str):
    name_m = re.search(r"Name of Establishment\s+(.+)", text, re.IGNORECASE)
    id_m   = re.search(r"Establishment Id\s+([A-Z0-9]+)", text, re.IGNORECASE)
    name = re.sub(r"\s+", " ", name_m.group(1)).strip() if name_m else "Unknown"
    name = re.split(r"\bLIN\b", name, flags=re.IGNORECASE)[0].strip()
    return (id_m.group(1).strip() if id_m else "Unknown"), (name or "Unknown")


def parse_pf_ecr(pdf, fname: str) -> dict:
    text = _page_text(pdf)
    estab_code, estab_name = _pf_entity(text)

    wage_m = re.search(r"Wage Month\s+([A-Za-z]{3,9}[-\s]\d{4})", text, re.IGNORECASE)
    month_upper, raw_year = _to_month_year(wage_m.group(1) if wage_m else "")
    fy_str, fy_start = _fy_from_month_year(month_upper, raw_year)

    epf, eps, epf_eps = _pf_totals(text)
    total_contribution = epf + eps + epf_eps

    members_m = re.search(r"Total Members\s+(\d+)", text, re.IGNORECASE)
    ecr_m     = re.search(r"ECR Id\s+(\d+)", text, re.IGNORECASE)
    trrn_m    = re.search(r"TRRN\s*(?:Number)?\s*:?\s*(\d+)", text, re.IGNORECASE)
    upl_m     = re.search(r"Uploaded Date Time\s+(\d{2}[-/][A-Za-z0-9]+[-/]\d{4})", text, re.IGNORECASE)

    return {
        "ReturnType":            "PF",
        "DocKind":               "Return",
        "EntityID":              estab_code,
        "EntityName":            estab_name,
        "FY":                    fy_str,
        "Total_EPF":             epf,
        "Total_EPS":             eps,
        "Total_EPF_EPS":         epf_eps,
        "Total_Contribution":    total_contribution,
        "PrimaryAmount":         total_contribution,
        "Total_Members":         int(members_m.group(1)) if members_m else 0,
        "ECR_Id":                ecr_m.group(1) if ecr_m else "",
        "TRRN":                  trrn_m.group(1) if trrn_m else "",
        "DocRef":                (ecr_m.group(1) if ecr_m else "") or (trrn_m.group(1) if trrn_m else ""),
        "FilingDate":            _norm_date(upl_m.group(1)) if upl_m else None,
        "PeriodDate":            _period_date(month_upper, fy_start),
        "Month":                 month_upper.title() if month_upper != "UNKNOWN" else "Unknown",
    }


def parse_pf_arrears(pdf, fname: str) -> dict:
    text = _page_text(pdf)
    estab_code, estab_name = _pf_entity(text)

    from_m = re.search(r"From Date\s+([A-Za-z]{3,9}[-\s]\d{4})", text, re.IGNORECASE)
    month_upper, raw_year = _to_month_year(from_m.group(1) if from_m else "")
    fy_str, fy_start = _fy_from_month_year(month_upper, raw_year)

    epf, eps, epf_eps = _pf_totals(text)
    total_contribution = epf + eps + epf_eps

    arr_m     = re.search(r"Arrear Id\s+(\d+)", text, re.IGNORECASE)
    members_m = re.search(r"Total Members\s+(\d+)", text, re.IGNORECASE)
    disb_m    = re.search(r"Disbursement Date\s+(\d{2}[-/][A-Za-z0-9]+[-/]\d{4})", text, re.IGNORECASE)

    return {
        "ReturnType":            "PF",
        "DocKind":               "Arrears",
        "EntityID":              estab_code,
        "EntityName":            estab_name,
        "FY":                    fy_str,
        "Total_EPF":             epf,
        "Total_EPS":             eps,
        "Total_EPF_EPS":         epf_eps,
        "Total_Contribution":    total_contribution,
        "PrimaryAmount":         total_contribution,
        "Total_Members":         int(members_m.group(1)) if members_m else 0,
        "Arrear_Id":             arr_m.group(1) if arr_m else "",
        "DocRef":                arr_m.group(1) if arr_m else "",
        "FilingDate":            _norm_date(disb_m.group(1)) if disb_m else None,
        "PeriodDate":            _period_date(month_upper, fy_start),
        "Month":                 month_upper.title() if month_upper != "UNKNOWN" else "Unknown",
    }


def parse_pf_payment(pdf, fname: str) -> dict:
    text = _page_text(pdf)

    def kv(key_pattern: str) -> str:
        m = re.search(rf"{key_pattern}\s*:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def kv_amt(key_pattern: str) -> float:
        raw = kv(key_pattern)
        m = re.search(r"[\d,]+(?:\.\d+)?", raw)
        return to_float(m.group(0)) if m else 0.0

    estab_id   = kv(r"Establishment ID") or "Unknown"
    estab_name = kv(r"Establishment Name") or "Unknown"
    month_upper, raw_year = _to_month_year(kv(r"Wage Month"))
    fy_str, fy_start = _fy_from_month_year(month_upper, raw_year)

    total   = kv_amt(r"Total Amount \(Rs\)")
    ac1     = kv_amt(r"Account-1 Amount \(Rs\)")
    ac2     = kv_amt(r"Account-2 Amount \(Rs\)")
    ac10    = kv_amt(r"Account-10 Amount \(Rs\)")
    ac21    = kv_amt(r"Account-21 Amount \(Rs\)")
    ac22    = kv_amt(r"Account-22 Amount \(Rs\)")

    trrn    = kv(r"TRRN(?:\s*No)?") or ""
    trrn    = re.sub(r"[^0-9].*$", "", trrn).strip()
    crn     = kv(r"CRN")
    status  = kv(r"Challan Status")
    bank    = kv(r"Payment Confirmation Bank")
    pay_dt  = kv(r"Payment Date")

    return {
        "ReturnType":            "PF",
        "DocKind":               "Payment",
        "EntityID":              estab_id,
        "EntityName":            estab_name,
        "FY":                    fy_str,
        "Total_Amount":          total,
        "PrimaryAmount":         total,
        "AC01":                  ac1,
        "AC02":                  ac2,
        "AC10":                  ac10,
        "AC21":                  ac21,
        "AC22":                  ac22,
        "TRRN":                  trrn,
        "CRN":                   crn,
        "Challan_Status":        status,
        "Bank":                  bank,
        "DocRef":                trrn or crn,
        "FilingDate":            _norm_date(pay_dt),
        "PeriodDate":            _period_date(month_upper, fy_start),
        "Month":                 month_upper.title() if month_upper != "UNKNOWN" else "Unknown",
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
    company_name = _strip_ms(re.sub(r"\s+", " ", block).strip())
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
        "DocKind":           "Return",
        "EntityID":          tin_val,
        "EntityName":        company_name,
        "FY":                fy_str,
        "Period":            f"{period_month} {period_year}" if period_year else "Unknown",
        "Total Tax Payable": total_tax,
        "Net Payable":       net_payable,
        "PT Paid":           pt_paid,
        "PrimaryAmount":     pt_paid,
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


# ── PTRC Challan (MTR Form 6) — the payment instrument ───────────────────────────
# Two sub-layouts:
#   v1 "MTR FORM NO.6":     Dept-ID <TIN>P; period as "01-05-2025 31-05-2025";
#                           amounts as "Amount of Tax 0 … Advance Payment 12,800 … Total 12,800"
#   v2 "MTR Form Number-6": TAX ID / TAN <TIN>P; "From 01/06/2025 To 30/06/2025";
#                           "AMOUNT OF TAX 13000.00 … Total 13,000.00"

def parse_ptrc_challan(pdf, fname: str) -> dict:
    text = _page_text(pdf)

    # ── TIN (strip trailing P/V registration suffix) ──
    tin_m = re.search(
        r"(?:Dept-ID|TAX ID\s*/\s*TAN(?:\s*\(If Any\))?)\s*[:\-]?\s*(\d{9,})",
        text, re.IGNORECASE,
    )
    tin_val = tin_m.group(1) if tin_m else "Unknown"

    # ── Company name (best-effort; reconciliation keys on TIN+period, not name) ──
    name_m = (re.search(r"Full Name\s*(?:of)?\s*(?:the Dealer)?\s*[:\-]?\s*(M\s*/?\s*S[.\s].+)", text, re.IGNORECASE)
              or re.search(r"Full Name\s*[:\-]?\s*(.+)", text, re.IGNORECASE))
    company_name = "Unknown"
    if name_m:
        raw = re.split(r"\b(?:From|To|Location|Flat|Premises)\b", name_m.group(1))[0]
        raw = re.sub(r"[^A-Za-z&/.,\- ]", " ", raw)
        company_name = _strip_ms(re.sub(r"\s+", " ", raw).strip()) or "Unknown"

    # ── Period (the challan states its own From/To) ──
    per_m = (re.search(r"From\s+(\d{2}/\d{2}/\d{4})\s+To\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
             or re.search(r"(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})", text))
    from_dt = _parse_date(per_m.group(1)) if per_m else None
    period_date = pd.Timestamp(from_dt.year, from_dt.month, 1) if from_dt is not None else None
    fy_str, _ = _fy_from_date(period_date)
    month_name = period_date.strftime("%B") if period_date is not None else "Unknown"

    # ── Amounts ──
    def amt(label: str) -> float:
        m = re.search(rf"{label}\s+([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
        return to_float(m.group(1)) if m else 0.0

    tax      = amt(r"Amount of Tax") or amt(r"AMOUNT OF TAX")
    interest = amt(r"Interest Amount")
    penalty  = amt(r"Penalty Amount")
    advance  = amt(r"Advance Payment")
    fees     = amt(r"\bFees\b")
    total_m  = re.search(r"\bTotal\s+([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    total    = to_float(total_m.group(1)) if total_m else 0.0

    # ── Refs ──
    grn_m = re.search(r"GRN\s+([A-Z]{2}[A-Z0-9]{6,})", text)         # v2 real GRN; v1 has none
    cin_m = re.search(r"CIN(?:\s*Ref)?\.?\s*No\.?\s*[:\-]?\s*(\w{10,})", text, re.IGNORECASE)
    urn_m = re.search(r"(URN\w+)", text)
    brn_m = re.search(r"BRN\s*No\.?\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
    dt_m  = re.search(r"\bDate\s+(\d{2}[-/]\d{2}[-/]\d{4})", text)

    doc_ref = (cin_m.group(1) if cin_m else "") or (grn_m.group(1) if grn_m else "") \
              or (urn_m.group(1) if urn_m else "")

    return {
        "ReturnType":      "PTRC",
        "DocKind":         "Challan",
        "EntityID":        tin_val,
        "EntityName":      company_name,
        "FY":              fy_str,
        "Period":          month_name + (f" {period_date.year}" if period_date is not None else ""),
        "Amount_of_Tax":   tax,
        "Interest":        interest,
        "Penalty":         penalty,
        "Advance_Payment": advance,
        "Fees":            fees,
        "Total":           total,
        "PrimaryAmount":   total,
        "GRN":             grn_m.group(1) if grn_m else "",
        "CIN":             cin_m.group(1) if cin_m else "",
        "URN":             urn_m.group(1) if urn_m else "",
        "BRN":             brn_m.group(1) if brn_m else "",
        "DocRef":          doc_ref,
        "FilingDate":      _norm_date(dt_m.group(1)) if dt_m else None,
        "PeriodDate":      period_date,
        "Month":           month_name,
    }


# ── eBRC (Electronic Bank Realisation Certificate) ───────────────────────────────
# DGFT "STATEMENT OF BANK REALISATION" — proof that an export invoice's foreign
# payment was realised through a bank. Clean numbered fields (1–15).

def parse_ebrc(pdf, fname: str) -> dict:
    text = _page_text(pdf)

    def after(label: str, pat: str = r"(.+)") -> str:
        m = re.search(rf"{label}\s+{pat}", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    firm    = after(r"Firm Name")
    gstin_m = re.search(r"GSTIN\s*[-:]?\s*([0-9A-Z]{15})", text)
    gstin   = gstin_m.group(1) if gstin_m else ""
    iec     = after(r"\bIEC\b", r"(\w+)")
    sb_no   = after(r"Shipping Bill\s*/\s*Invoice No\.?", r"(\w+)")
    sb_date = after(r"Shipping Bill\s*/\s*Invoice Date", r"(\d{2}-\d{2}-\d{4})")
    bank    = after(r"Bank Name")
    bill_id = after(r"Bill ID No\.?", r"(\S+)")
    gst_inv_no   = after(r"GST Invoice No", r"(\S+)")
    gst_inv_date = after(r"GST Invoice Date", r"(\d{2}-\d{2}-\d{4})")

    # BRC No + realisation date are label-anchored (their field NUMBER shifts
    # between the two DGFT layouts, so never anchor on the number). The value
    # sits on the "<n> <value>" line embedded in the wrapped label.
    brc_m   = re.search(r"Bank Realisation Certificate[\s\S]{0,60}?([A-Z]{4}\d[0-9A-Z]{8,})", text, re.IGNORECASE)
    brc_no  = brc_m.group(1) if brc_m else ""
    real_m  = re.search(r"Date of Realisation of Money[\s\S]{0,40}?(\d{2}-\d{2}-\d{4})", text, re.IGNORECASE)
    real_dt = real_m.group(1) if real_m else ""

    total   = to_float(after(r"Total Realised Value", r"([\d,]+(?:\.\d+)?)"))
    net     = to_float(after(r"Net Realised Value",   r"([\d,]+(?:\.\d+)?)"))
    curr    = after(r"Currency of Realisation", r"([A-Z]{3})")
    print_dt = after(r"Date and Time of Printing", r"(\d{2}-\d{2}-\d{4})")

    # Deductions row: Commission / Discount / Insurance / Freight / Other
    ded_m = re.search(r"Deductions\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", text, re.IGNORECASE)
    ded = [to_float(x) for x in ded_m.groups()] if ded_m else [0.0] * 5

    # Shipping Bill Port wraps around its label; stitch the surrounding lines.
    port = ""
    pm = re.search(r"(.*)\n\d*\s*Shipping Bill Port\s*\n(.*)", text, re.IGNORECASE)
    if pm:
        port = re.sub(r"\s+", " ", (pm.group(1).split("\n")[-1] + " " + pm.group(2).split("\n")[0])).strip()

    real_ts = _parse_date(real_dt)
    if real_ts is not None and pd.isna(real_ts):
        real_ts = None
    fy_str, _ = _fy_from_date(real_ts)
    period_date = pd.Timestamp(real_ts.year, real_ts.month, 1) if real_ts is not None else None

    return {
        "ReturnType":        "EBRC",
        "DocKind":           "Return",
        "EntityID":          iec or gstin or "Unknown",
        "EntityName":        firm or "Unknown",
        "FY":                fy_str,
        "GSTIN":             gstin,
        "IEC":               iec,
        "ShippingBill_No":   sb_no,
        "ShippingBill_Date": _norm_date(sb_date),
        "ShippingBill_Port": port,
        "Bank_Name":         bank,
        "Bill_ID":           bill_id,
        "GST_Invoice_No":    gst_inv_no,
        "GST_Invoice_Date":  _norm_date(gst_inv_date),
        "BRC_No":            brc_no,
        "Realisation_Date":  _norm_date(real_dt),
        "Total_Realised":    total,
        "Commission":        ded[0],
        "Discount":          ded[1],
        "Insurance":         ded[2],
        "Freight":           ded[3],
        "Other_Deduction":   ded[4],
        "Net_Realised":      net,
        "PrimaryAmount":     net,
        "Currency":          curr,
        "Print_Date":        _norm_date(print_dt),
        "DocRef":            brc_no or bill_id,
        "FilingDate":        _norm_date(real_dt),
        "PeriodDate":        period_date,
        "Month":             period_date.strftime("%B") if period_date is not None else "Unknown",
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
