"""ICEGATE Shipping Bill parser (browser-safe core).

Parses Indian Customs EDI System (ICES) shipping bill PDFs into a structured
dict with built-in cross-validation. Adapted from the standalone sb_parser.py:
no OCR, no Excel, no CLI - just parse + validate, Pyodide-friendly.

Robustness notes:
  * The diagonal "ASSESSED COPY" watermark and rotated sidebar labels overlap
    real content; every char whose PDF matrix has a rotation component is
    dropped before text is assembled.
  * Reading order is rebuilt by clustering words on coordinates, never the
    PDF stream order.
  * Box values are located by x-coordinate zones anchored on printed labels.
  * Item rows use rightmost-anchored patterns (descriptions contain numbers).
  * Values below 1 print without a leading zero (".81").
  * The PART-II invoice identity row repeats on continuation pages and is
    deduplicated by (sno, invoice_no).
"""

import re
from collections import defaultdict


# ── extraction layer ──────────────────────────────────────────────────────────

def _keep_upright(obj):
    if obj.get("object_type") != "char":
        return True
    m = obj.get("matrix")
    if m and (abs(m[1]) > 0.001 or abs(m[2]) > 0.001):
        return False
    return True


def page_words(page):
    return page.filter(_keep_upright).extract_words(x_tolerance=1.2, y_tolerance=2.0)


def cluster_lines(words, tol=2.5):
    lines = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if lines and abs(w["top"] - lines[-1]["top"]) <= tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["text"] = " ".join(w["text"] for w in ln["words"])
    return lines


def words_in_box(words, x0, top, x1, bottom):
    return [w for w in words
            if w["x0"] >= x0 - 1 and w["x1"] <= x1 + 1
            and top - 1 <= w["top"] <= bottom + 1]


def box_lines(words, x0, top, x1, bottom):
    return cluster_lines(words_in_box(words, x0, top, x1, bottom))


def find_line(lines, pattern):
    rx = re.compile(pattern)
    for i, ln in enumerate(lines):
        if rx.search(ln["text"]):
            return i, ln
    return None, None


def find_word(words, pattern):
    rx = re.compile(pattern)
    for w in words:
        if rx.match(w["text"]):
            return w
    return None


def zone_split(anchor_words, value_words, left_slack=8.0):
    anchors = sorted(anchor_words, key=lambda w: w["x0"])
    bounds = [a["x0"] - left_slack for a in anchors] + [1e9]
    zones = defaultdict(list)
    for vw in sorted(value_words, key=lambda w: w["x0"]):
        cx = (vw["x0"] + vw["x1"]) / 2
        zi = None
        for i in range(len(anchors)):
            if bounds[i] <= cx < bounds[i + 1]:
                zi = i
                break
        if zi is None and cx >= bounds[-2]:
            zi = len(anchors) - 1
        if zi is not None:
            zones[zi].append(vw["text"])
    return {i: " ".join(v) for i, v in zones.items()}


# ── helpers ───────────────────────────────────────────────────────────────────

NUM = r"-?(?:[\d,]+(?:\.\d+)?|\.\d+)"
DATE_RX = r"\d{2}-[A-Z]{3}-\d{2,4}"


def to_num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if not re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\.\d+)", s):
        return None
    f = float(s)
    return int(f) if f.is_integer() else f


def clean_address(block_lines):
    out = []
    for t in block_lines:
        t = re.split(r"\s\d+\.\s*[A-Za-z]", " " + t)[0].strip()
        t = t.strip("` ").strip()
        if t and not re.match(r"^\d+\.\s*[A-Za-z]", t):
            out.append(t)
    if not out:
        return None
    return {"name": out[0], "address": " ".join(out[1:]) or None}


# ── section parsers ───────────────────────────────────────────────────────────

def parse_header(lines):
    h = {}
    for ln in lines[:14]:
        t = ln["text"]
        m = re.search(r"INDIAN CUSTOMS EDI SYSTEM\s+(\S+)\s+(\d{6,8})\s+(" + DATE_RX + ")", t)
        if m:
            h["port_code"], h["sb_no"], h["sb_date"] = m.group(1), m.group(2), m.group(3)
        m = re.search(r"IEC/Br\s+(\d+)\s*(\d*)", t)
        if m:
            h["iec"] = m.group(1)
            h["iec_branch"] = m.group(2) or None
        m = re.search(r"GSTIN/TYPE\s+(\S+)\s*(\S*)", t)
        if m:
            h["gstin"], h["gstin_type"] = m.group(1), m.group(2) or None
        m = re.search(r"CB CODE\s+(\S+)", t)
        if m:
            h["cb_code"] = m.group(1)
        m = re.search(r"^Nos\s+(\d+)\s+(\d+)\s+(\d+)", t)
        if m:
            h["counts"] = {"invoices": int(m.group(1)),
                           "items": int(m.group(2)),
                           "containers": int(m.group(3))}
        m = re.search(r"^(.*?)\s*PKG\s+(" + NUM + r")\s+G\.WT\s*KGS\s+(" + NUM + r")\s*(\*\S+)?", t)
        if m:
            h["customs_location"] = m.group(1).strip() or None
            h["packages"] = to_num(m.group(2))
            h["gross_weight_kg"] = to_num(m.group(3))
            h["sb_barcode"] = (m.group(4) or "").lstrip("*") or None
    return h


FLAG_KEYS = ["MODE", "ASSESS", "EXMN", "JOBBING", "MEIS", "DBK", "RODTP",
             "LICENCE", "DFRC", "RE-EXP", "LUT"]


def parse_part1(lines, words):
    p = {}
    i, hdr = find_line(lines, r"1\.MODE\s+2\.ASSESS")
    if hdr is not None:
        anchors = [w for w in hdr["words"] if re.match(r"^\d+\.", w["text"])]
        if i + 1 < len(lines) and len(anchors) >= 8:
            vals = zone_split(anchors, lines[i + 1]["words"])
            flags = {}
            for zi, key in enumerate(FLAG_KEYS[:len(anchors)]):
                flags[key] = vals.get(zi)
            p["mode"] = flags.pop("MODE", None)
            p["scheme_flags"] = flags

    joined = "\n".join(ln["text"] for ln in lines)

    m = re.search(r"12\.PORT OF LOADING\s*([A-Z0-9]+)\s*\(([^)]*)\)\s*"
                  r"13\.COUNTRY\s*OF\s*FINAL\s*DESTINATION\s*(.+)", joined)
    if m:
        p["port_of_loading"] = {"code": m.group(1), "name": m.group(2)}
        p["country_of_final_destination"] = m.group(3).strip()
    m = re.search(r"14\.STATE OF ORIGIN\s+(.+?)\s+15\.PORT OF FINAL", joined)
    if m:
        p["state_of_origin"] = m.group(1).strip()
    m = re.search(r"15\.PORT OF FINAL\s*DESTINATION\s*([A-Z0-9]+)\s*(?:\(([^)]*)\))?", joined)
    if m:
        p["port_of_final_destination"] = {"code": m.group(1), "name": m.group(2)}
    m = re.search(r"16\.PORT OF DISCHARGE\s*([A-Z0-9]+)\s*(?:\(([^)]*)\))?\s*"
                  r"17\.COUNTRY OF DISCHARGE\s*(.+)", joined)
    if m:
        p["port_of_discharge"] = {"code": m.group(1), "name": m.group(2)}
        p["country_of_discharge"] = m.group(3).strip()

    exp_lbl = find_word(words, r"1\.EXPORTER'S")
    con_lbl = find_word(words, r"7\.CONSIGNEE")
    ad_i, ad_ln = find_line(lines, r"3\.\s*AD CODE")
    if exp_lbl:
        bottom = ad_ln["top"] - 1 if ad_ln else exp_lbl["bottom"] + 50
        blk = box_lines(words, 40, exp_lbl["bottom"] + 1, 308, bottom)
        p["exporter"] = clean_address([l["text"] for l in blk])
    if con_lbl:
        blk = box_lines(words, 310, con_lbl["bottom"] + 1, 600, con_lbl["bottom"] + 58)
        p["consignee"] = clean_address([l["text"] for l in blk])

    m = re.search(r"3\.\s*AD CODE:?\s*\D*(\d{6,8})", joined)
    if m:
        p["ad_code"] = m.group(1)
    m = re.search(r"5\.CB NAME\s+(.+?)(?:\s*10\.DBK BANK.*)?$", joined, re.M)
    if m:
        p["cb_name"] = m.group(1).strip()
    m = re.search(r"9\.FOREX BANK A/C NO\.?\s*(\S+)", joined)
    if m:
        p["forex_bank_ac"] = m.group(1)
    m = re.search(r"10\.DBK BANK A/C NO\.?\s*(\S+)", joined)
    if m:
        p["dbk_bank_ac"] = m.group(1)

    vi, vhdr = find_line(lines, r"1\.FOB VALUE\s+2\.FREIGHT")
    if vhdr is not None:
        anchors = [w for w in vhdr["words"] if re.match(r"^\d\.", w["text"])]
        row = words_in_box(words, 30, vhdr["top"] + 3, 600, vhdr["top"] + 16)
        vals = zone_split(anchors, [w for w in row if to_num(w["text"]) is not None])
        keys = ["fob_value_inr", "freight_inr", "insurance_inr",
                "discount_inr", "commission_inr"]
        for zi, key in enumerate(keys[:len(anchors)]):
            if vals.get(zi) is not None:
                nums = [to_num(x) for x in vals[zi].split()]
                nums = [n for n in nums if n is not None]
                if len(nums) == 1:
                    p[key] = nums[0]
                elif len(nums) > 1:
                    for k2, n2 in zip(keys[zi:], nums):
                        p.setdefault(k2, n2)

    dbk_lbl = find_word(words, r"^1\.DBK$")
    if dbk_lbl and dbk_lbl["x0"] > 300:
        band = words_in_box(words, dbk_lbl["x0"] - 40, dbk_lbl["bottom"],
                            dbk_lbl["x0"] + 130, dbk_lbl["bottom"] + 22)
        nums = [to_num(w["text"]) for w in band if to_num(w["text"]) is not None]
        if nums:
            p["dbk_claim"] = nums[0]
    m = re.search(r"5\.RODTEP AMT\s*6\.ROSCTL AMT\s*(" + NUM + r")\s+(" + NUM + ")", joined)
    if m:
        p["rodtep_amt"], p["rosctl_amt"] = to_num(m.group(1)), to_num(m.group(2))
    m = re.search(r"2\.\s*IGST AMT\s*(" + NUM + ")", joined)
    if m:
        p["igst_amt"] = to_num(m.group(1))

    i, hdr = find_line(lines, r"1\.SEAL TYPE\s+2\.NATURE OF CARGO")
    if hdr is not None and i + 1 < len(lines):
        anchors = [w for w in hdr["words"] if re.match(r"^\d\.", w["text"])]
        vals = zone_split(anchors, lines[i + 1]["words"])
        p["cargo"] = {"seal_type": vals.get(0), "nature": vals.get(1),
                      "packets": to_num(vals.get(2)),
                      "containers": to_num(vals.get(3)),
                      "loose_packets": to_num(vals.get(4))}

    i, ln = find_line(lines, r"6\.MARKS\s*&\s*NUMBERS")
    if ln is not None:
        chunk = [re.sub(r"^6\.MARKS\s*&\s*NUMBERS\s*", "", ln["text"])]
        for nxt in lines[i + 1:i + 4]:
            if re.match(r"^(Glossary|GLOSSARY|Scan QR|[A-Z]:\s|1\.EVENT)", nxt["text"]):
                break
            chunk.append(nxt["text"])
        marks = " ".join(chunk).strip()
        p["marks_and_numbers"] = marks or None
        m = re.search(r"LUT No\.?\s*&?\s*Date\s*:?\s*(\S+?)\s*F?\s*Dt\.?\s*([\d\- ]{4,14})",
                      marks)
        if m:
            p["lut"] = {"no": m.group(1),
                        "date": m.group(2).replace(" ", "").strip("-") or None}

    proc = {}
    for ev, rx in [("submission", r"Submission"), ("assessment", r"Assessment"),
                   ("examination", r"Examination"), ("leo", r"^9\.LEO")]:
        for ln in lines:
            m = re.search(rx + r"\s+(" + DATE_RX + r")\s*(\d{1,2}:\d{2})?", ln["text"])
            if m:
                proc[ev] = {"date": m.group(1), "time": m.group(2)}
                break
    m = re.search(r"4\.LEO NO\.?\s*(\d{6,})", joined)
    if m:
        proc.setdefault("leo", {})["no"] = m.group(1)
    m = re.search(r"6\.LEO Date\.?\s*(" + DATE_RX + ")", joined)
    if m:
        proc.setdefault("leo", {})["date"] = m.group(1)
    if proc:
        p["process"] = proc
    m = re.search(r"^(\d{2}[A-Z]{4}\d{14,18})\s+(" + DATE_RX + r")\s+(\S+)", joined, re.M)
    if m:
        p["cin"] = {"no": m.group(1), "date": m.group(2), "site": m.group(3)}
    return p


INV_ROW_RX = re.compile(r"^(\d{1,2})\s+(\S*/\S+)\s+(\d{2}/\d{2}/\d{4})\b(.*)$")
ITEM2_START_RX = re.compile(r"^(\d{1,3})\s+(\d{8})\s+(.+)$")
RIGHT_ANCHOR_RX = re.compile(
    r"^(.*?)\s+(" + NUM + r")\s+([A-Z]{2,4})\s+(" + NUM + r")\s+(" + NUM + r")$")
INCOTERMS = {"FOB", "CIF", "CF", "CFR", "C&F", "CI", "FCA", "EXW", "DDP",
             "DAP", "CPT", "CIP", "FAS", "DDU", "DPU"}


def parse_part2_page(lines, words, invoices):
    inv = None
    i_hdr, _ = find_line(lines, r"1\.S\.No\s+2\.INVOICE")
    if i_hdr is not None:
        for ln in lines[i_hdr + 1:i_hdr + 4]:
            m = INV_ROW_RX.match(ln["text"])
            if m:
                inv = {"sno": int(m.group(1)), "invoice_no": m.group(2),
                       "invoice_date": m.group(3)}
                rest = m.group(4).split()
                terms = [t for t in rest if t in INCOTERMS]
                if terms:
                    inv["terms"] = terms[-1]
                break
    if inv is None:
        inv = invoices[-1] if invoices else None
        if inv is None:
            return
        continuation = True
    else:
        existing = next((x for x in invoices
                         if x.get("sno") == inv["sno"]
                         and x.get("invoice_no") == inv["invoice_no"]), None)
        if existing is not None:
            inv = existing
            continuation = True
        else:
            continuation = False
            invoices.append(inv)

    if not continuation:
        buy_lbl = find_word(words, r"^2\.BUYER'S$")
        tp_i, tp_ln = find_line(lines, r"3\.THIRD PARTY NAME")
        if buy_lbl:
            bottom = tp_ln["top"] - 1 if tp_ln else buy_lbl["bottom"] + 50
            blk = box_lines(words, 300, buy_lbl["bottom"] + 1, 600, bottom)
            inv["buyer"] = clean_address([l["text"] for l in blk])
        vi, vhdr = find_line(lines, r"1\.INVOICE VALUE\s+2\.FOB VALUE")
        if vhdr is not None:
            band = words_in_box(words, 40, vhdr["top"] + 3, 600, vhdr["top"] + 26)
            band_lines = cluster_lines(band)
            band_text = "\n".join(bl["text"] for bl in band_lines)
            for bl in band_lines:
                toks = [w["text"] for w in bl["words"]]
                tail = None
                for j in range(len(toks) - 3):
                    if (toks[j] == "1" and re.fullmatch(r"[A-Z]{3}", toks[j + 1])
                            and toks[j + 2] == "INR"
                            and to_num(toks[j + 3]) is not None):
                        tail = j
                        break
                if tail is None:
                    continue
                inv["currency"] = toks[tail + 1]
                inv["exchange_rate"] = to_num(toks[tail + 3])
                nums = [to_num(t) for t in toks[:tail]]
                nums = [n for n in nums if n is not None]
                for k, v in zip(["invoice_value", "fob_value", "freight",
                                 "insurance", "discount", "commission",
                                 "deduction"], nums):
                    inv[k] = v
                break
            if "currency" not in inv:
                m = re.search(r"^([A-Z]{3})\s+[A-Z]{3}\b", band_text, re.M)
                if m:
                    inv["currency"] = m.group(1)
            if "invoice_value" not in inv:
                for bl in band_lines:
                    nums = [to_num(w["text"]) for w in bl["words"]
                            if to_num(w["text"]) is not None]
                    if len(nums) >= 2:
                        inv["invoice_value"], inv["fob_value"] = nums[0], nums[1]
                        break

    items = inv.setdefault("items", [])
    i_it, it_hdr = find_line(lines, r"1\.ItemSNo\s+2\.HS CD")
    if it_hdr is None:
        return
    cur = None
    for ln in lines[i_it + 1:]:
        t = ln["text"]
        if re.match(r"^(Glossary|GLOSSARY|Scan QR|Visit ICEGATE|Page \d+ Of|A:\s|FOB - )", t):
            break
        m = ITEM2_START_RX.match(t)
        if m and to_num(m.group(1)) is not None:
            body = m.group(3)
            ra = RIGHT_ANCHOR_RX.match(body)
            cur = {"sno": int(m.group(1)), "hs_code": m.group(2)}
            if ra:
                cur["description"] = ra.group(1).strip()
                cur["quantity"] = to_num(ra.group(2))
                cur["uqc"] = ra.group(3)
                cur["rate"] = to_num(ra.group(4))
                cur["value_fc"] = to_num(ra.group(5))
            else:
                cur["description"] = body.strip()
            items.append(cur)
        elif cur is not None:
            cur["description"] = (cur.get("description", "") + " " + t).strip()


ITEM3_HDR_RX = re.compile(r"^1INVSN\s+2ITEMSN")
ITEM3_ROW_RX = re.compile(r"^(\d{1,2})\s+(\d{1,3})\s+(\d{8})(.+)$")
ITEM3_NUMS_RX = re.compile(
    r"^(.*?)\s+(" + NUM + r")\s+([A-Z]{2,4})\s+(" + NUM + r")\s+(" + NUM +
    r")\s+(" + NUM + r")\s+(" + NUM + r")$")


def parse_part3_page(lines, items):
    i = 0
    n = len(lines)
    while i < n:
        if not ITEM3_HDR_RX.match(lines[i]["text"]):
            i += 1
            continue
        i += 1
        if i >= n:
            break
        m = ITEM3_ROW_RX.match(lines[i]["text"])
        if not m:
            continue
        item = {"invoice_sno": int(m.group(1)), "item_sno": int(m.group(2)),
                "hs_code": m.group(3)}
        body = m.group(4)
        mn = ITEM3_NUMS_RX.match(body)
        if mn:
            item["description"] = mn.group(1).strip()
            item["quantity"] = to_num(mn.group(2))
            item["uqc"] = mn.group(3)
            item["rate"] = to_num(mn.group(4))
            item["value_fc"] = to_num(mn.group(5))
            item["fob_inr"] = to_num(mn.group(6))
            item["pmv"] = to_num(mn.group(7))
        else:
            item["description"] = body.strip()
        i += 1
        while i < n and not re.match(r"^11\.DUTYAMT", lines[i]["text"]):
            item["description"] = (item.get("description", "") + " " +
                                   lines[i]["text"]).strip()
            i += 1
        if i < n:
            i += 1
            if i < n and not lines[i]["text"].startswith("19."):
                toks = lines[i]["text"].split()
                for t in toks:
                    if t in ("Y", "N") and "dbk_claimed" not in item:
                        item["dbk_claimed"] = t
                    elif t in ("LUT", "PAID", "NP", "P") and "igst_status" not in item:
                        item["igst_status"] = t
                    elif to_num(t) is not None and "scheme_code" not in item:
                        item["scheme_code"] = str(t)
                i += 1
        if i < n and lines[i]["text"].startswith("19."):
            hdr = lines[i]
            anchors = [w for w in hdr["words"]
                       if re.match(r"^(19\.|20\.|21\.|22\.|23\.)$", w["text"])]
            i += 1
            if i < n and anchors and not lines[i]["text"].startswith("24."):
                vals = zone_split(anchors, lines[i]["words"])
                item["scheme_description"] = vals.get(0)
                item["sqc_msr"] = to_num(vals.get(1))
                item["sqc_uqc"] = vals.get(2)
                item["state_of_origin"] = vals.get(3)
                item["district_of_origin"] = vals.get(4)
                i += 1
        if i < n and lines[i]["text"].startswith("24."):
            hdr = lines[i]
            anchors = [w for w in hdr["words"]
                       if re.match(r"^(24\.|25\.COMP|26\.END|27\.FTA|28\.|29\.)", w["text"])]
            i += 1
            if i < n and anchors:
                vals = zone_split(anchors, lines[i]["words"])
                item["pt_abroad"] = vals.get(0)
                item["comp_cess"] = vals.get(1)
                item["end_use"] = vals.get(2)
                item["fta_benefit"] = vals.get(3)
                item["reward_benefit"] = vals.get(4)
                item["third_party_item"] = vals.get(5)
                i += 1
        items.append(item)


DBK_ROW_RX = re.compile(
    r"^(\d{1,2})\s+(\d{1,3})\s+(\w+)\s+(" + NUM + r")\s+(" + NUM + r")\s+(" +
    NUM + r")\s+(" + NUM + r")(?:\s+(" + NUM + r")\s+(" + NUM + r")\s+(" +
    NUM + r"))?$")
RODTEP_ROW_RX = re.compile(
    r"^(\d{1,2})\s+(\d{1,3})\s+(" + NUM + r")\s+([A-Z]{2,4})\s+(" + NUM +
    r")\s+(" + NUM + r")$")
CONT_ROW_RX = re.compile(r"^(\d{1,3})\s+([A-Z]{4}\d{7})\s+(\S+)\s+(" + DATE_RX + r")$")
HINV_ROW_RX = re.compile(r"^(\d{1,2})\s+(\S+)\s+(" + NUM + r")\s+([A-Z]{3})$")


def parse_part4_page(lines, doc):
    section = None
    for ln in lines:
        t = ln["text"]
        if re.search(r"A\.\s*DRAWBACK\s*&\s*ROSL", t):
            section = "dbk"
            continue
        if re.search(r"B\.\s*AA\s*/\s*DFIA", t):
            section = None
            continue
        if re.search(r"M\.\s*RODTEP DETAILS", t):
            section = "rodtep"
            continue
        if re.search(r"H\.\s*INVOICE DETAILS", t):
            section = "hinv"
            continue
        if re.search(r"I\.\s*CONTAINER DETAILS", t):
            section = "cont"
            continue
        if re.search(r"^[A-Z]\.\s*[A-Z]|^[A-Z]\.[A-Z0-9]", t) and len(t) < 60 \
                and not re.match(r"^\d", t):
            if not any(k in t for k in ("DRAWBACK", "RODTEP", "INVOICE DETAILS",
                                        "CONTAINER DETAILS")):
                section = None
            continue
        if section == "dbk":
            m = DBK_ROW_RX.match(t)
            if m:
                doc["drawback"].append({
                    "invoice_sno": int(m.group(1)), "item_sno": int(m.group(2)),
                    "dbk_sno": m.group(3), "qty_wt": to_num(m.group(4)),
                    "value": to_num(m.group(5)), "rate": to_num(m.group(6)),
                    "dbk_amount": to_num(m.group(7)),
                    "state_levy": to_num(m.group(8)),
                    "central_levy": to_num(m.group(9)),
                    "rosctl_amount": to_num(m.group(10))})
        elif section == "rodtep":
            m = RODTEP_ROW_RX.match(t)
            if m:
                doc["rodtep"].append({
                    "invoice_sno": int(m.group(1)), "item_sno": int(m.group(2)),
                    "quantity": to_num(m.group(3)), "uqc": m.group(4),
                    "units": to_num(m.group(5)), "value": to_num(m.group(6))})
        elif section == "cont":
            m = CONT_ROW_RX.match(t)
            if m:
                doc["containers"].append({
                    "sno": int(m.group(1)), "container_no": m.group(2),
                    "seal_no": m.group(3), "date": m.group(4)})
        elif section == "hinv":
            m = HINV_ROW_RX.match(t)
            if m:
                doc["invoice_summary"].append({
                    "sno": int(m.group(1)), "invoice_no": m.group(2),
                    "amount": to_num(m.group(3)), "currency": m.group(4)})


# ── assembly & validation ─────────────────────────────────────────────────────

PART_RX = re.compile(r"PART\s*-\s*(I{1,3}|IV|V)\s*-")


def classify_page(lines):
    for ln in lines[:16]:
        m = PART_RX.search(ln["text"])
        if m:
            return m.group(1)
    return None


def validate(doc):
    checks = []

    def chk(name, expected, actual, tol=0.011):
        if expected is None or actual is None:
            checks.append({"check": name, "ok": None,
                           "expected": expected, "actual": actual})
            return
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            ok = abs(expected - actual) <= max(tol, abs(expected) * 1e-6)
        else:
            ok = expected == actual
        checks.append({"check": name, "ok": ok,
                       "expected": expected, "actual": actual})

    counts = doc.get("counts") or {}
    chk("invoice_count", counts.get("invoices"), len(doc["invoices"]) or None)
    n_items3 = len(doc["items"])
    chk("item_count_part3", counts.get("items"), n_items3 or None)
    n_items2 = sum(len(i.get("items", [])) for i in doc["invoices"])
    chk("item_count_part2", counts.get("items"), n_items2 or None)
    if counts.get("containers"):
        chk("container_count", counts.get("containers"),
            len(doc["containers"]) or None)
    fob_sum = sum(it.get("fob_inr") or 0 for it in doc["items"])
    chk("fob_total_vs_item_sum", doc.get("fob_value_inr"),
        round(fob_sum, 2) if fob_sum else None, tol=1.0)
    if doc.get("dbk_claim") is not None:
        dbk_sum = sum(d.get("dbk_amount") or 0 for d in doc["drawback"])
        chk("dbk_claim_vs_sum", doc.get("dbk_claim"),
            round(dbk_sum, 2) if dbk_sum else None, tol=1.0)
    if doc.get("rodtep_amt"):
        r_sum = sum(r.get("value") or 0 for r in doc["rodtep"])
        chk("rodtep_amt_vs_sum", doc.get("rodtep_amt"),
            round(r_sum, 2) if r_sum else None, tol=1.0)
    for inv in doc["invoices"]:
        v_sum = sum(it.get("value_fc") or 0 for it in inv.get("items", []))
        chk(f"invoice_{inv.get('sno')}_value_vs_items",
            inv.get("invoice_value"), round(v_sum, 2) if v_sum else None,
            tol=max(1.0, (inv.get("invoice_value") or 0) * 0.001))

    evaluated = [c for c in checks if c["ok"] is not None]
    passed = sum(1 for c in evaluated if c["ok"])
    doc["validation"] = {
        "checks": checks,
        "passed": passed,
        "evaluated": len(evaluated),
        "score": round(passed / len(evaluated), 3) if evaluated else 0.0,
    }


CORE_FIELDS = ["sb_no", "sb_date", "port_code", "iec", "gstin",
               "port_of_loading", "country_of_final_destination",
               "exporter", "consignee", "fob_value_inr"]


def parse_shipping_bill(pdf, fname):
    """Parse an open pdfplumber PDF of an ICEGATE shipping bill.

    Returns the structured doc dict (same shape as sb_parser.py, minus OCR)."""
    doc = {"file": fname, "status": "parsed",
           "invoices": [], "items": [], "drawback": [], "rodtep": [],
           "containers": [], "invoice_summary": [], "warnings": []}

    header_done = False
    for pageno, page in enumerate(pdf.pages, 1):
        words = page_words(page)
        lines = cluster_lines(words)
        if not lines:
            continue
        if not header_done:
            h = parse_header(lines)
            if h.get("sb_no"):
                doc.update(h)
                header_done = True
        part = classify_page(lines)
        try:
            if part == "I":
                doc.update(parse_part1(lines, words))
            elif part == "II":
                parse_part2_page(lines, words, doc["invoices"])
            elif part == "III":
                parse_part3_page(lines, doc["items"])
            elif part == "IV":
                parse_part4_page(lines, doc)
        except Exception as e:
            doc["warnings"].append(f"page {pageno} ({part}): {e}")
    doc["pages"] = len(pdf.pages)

    missing = [f for f in CORE_FIELDS if not doc.get(f)]
    if missing:
        doc["warnings"].append("missing core fields: " + ", ".join(missing))
    validate(doc)
    return doc


def sb_flat_row(doc):
    """One flat row per bill for SB_Details.csv."""
    v = doc.get("validation", {})
    leo = ((doc.get("process") or {}).get("leo") or {})
    return {
        "SB_No": doc.get("sb_no"),
        "SB_Date": doc.get("sb_date"),
        "Port": doc.get("port_code"),
        "Customs_Location": doc.get("customs_location"),
        "Mode": doc.get("mode"),
        "IEC": doc.get("iec"),
        "GSTIN": doc.get("gstin"),
        "Exporter": (doc.get("exporter") or {}).get("name"),
        "Consignee": (doc.get("consignee") or {}).get("name"),
        "Country_Destination": doc.get("country_of_final_destination"),
        "Port_Loading": (doc.get("port_of_loading") or {}).get("code"),
        "Port_Discharge": (doc.get("port_of_discharge") or {}).get("code"),
        "Invoices": len(doc.get("invoices", [])),
        "Items": len(doc.get("items", [])),
        "Containers": len(doc.get("containers", [])),
        "Packages": doc.get("packages"),
        "Gross_Wt_Kg": doc.get("gross_weight_kg"),
        "FOB_INR": doc.get("fob_value_inr"),
        "Freight_INR": doc.get("freight_inr"),
        "Insurance_INR": doc.get("insurance_inr"),
        "DBK_Claim": doc.get("dbk_claim"),
        "RODTEP_Amt": doc.get("rodtep_amt"),
        "ROSCTL_Amt": doc.get("rosctl_amt"),
        "LUT_No": (doc.get("lut") or {}).get("no"),
        "LEO_Date": leo.get("date"),
        "CB_Name": doc.get("cb_name"),
        "Checks_Passed": v.get("passed"),
        "Checks_Run": v.get("evaluated"),
        "Warnings": "; ".join(doc.get("warnings", [])) or None,
    }


def sb_item_rows(doc):
    """Item rows for SB_Items.csv (one per Part-III line item)."""
    inv_by_sno = {i.get("sno"): i for i in doc.get("invoices", [])}
    rows = []
    for it in doc.get("items", []):
        inv = inv_by_sno.get(it.get("invoice_sno"), {})
        rows.append({
            "SB_No": doc.get("sb_no"),
            "SB_Date": doc.get("sb_date"),
            "Invoice_No": inv.get("invoice_no"),
            "Item_SNo": it.get("item_sno"),
            "HS_Code": it.get("hs_code"),
            "Description": it.get("description"),
            "Quantity": it.get("quantity"),
            "UQC": it.get("uqc"),
            "Rate": it.get("rate"),
            "Value_FC": it.get("value_fc"),
            "Currency": inv.get("currency"),
            "FOB_INR": it.get("fob_inr"),
            "IGST_Status": it.get("igst_status"),
            "Scheme": it.get("scheme_description"),
            "State_Origin": it.get("state_of_origin"),
        })
    return rows
