#!/usr/bin/env python3
"""Convertit WildReceipt (format PaddleOCR KIE) en vérité terrain JSON.

Entrée  : train.txt ou test.txt (une ligne JSON par reçu), class_mapping.json
Sortie  : un fichier .jsonl (un reçu par ligne) conforme à receipt_annotation_template.json

Principes :
- On ne devine jamais : valeur illisible ou ambiguë -> null + note dans meta.conversion_notes.
- Les textes de WildReceipt n'ont pas d'espaces : on les garde tels quels.
- Date jour/mois ambiguë (ex. 03/04/12) : value=null et les deux lectures dans alternatives.
- Champs avec plusieurs zones (policy any_of) : première valeur valide = référence,
  les autres valeurs distinctes sont rangées dans "alternatives".

Usage :
  python convert_wildreceipt.py --input test.txt --mapping class_mapping.json \
         --split test --out ground_truth_test.jsonl
"""
import argparse
import datetime as dt
import json
import re
import statistics
from collections import Counter, defaultdict

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

ITEM_DESC, ITEM_QTY, ITEM_PRICE = 11, 13, 15  # ids de class_list.txt


# --------------------------------------------------------------------------
# Géométrie
# --------------------------------------------------------------------------
def make_zone(a):
    xs, ys = a["box"][0::2], a["box"][1::2]
    return {
        "cx": sum(xs) / 4.0,
        "cy": sum(ys) / 4.0,
        "h": max(ys) - min(ys),
        "text": (a.get("text") or "").strip(),
        "label": a["label"],
    }


# --------------------------------------------------------------------------
# Analyse des valeurs. Chaque fonction renvoie (valeur | None, note | None)
# --------------------------------------------------------------------------
NUM_TOKEN = re.compile(r"\d[\d.,]*\d|\d")


def parse_amount(text):
    t = text.strip()
    tokens = NUM_TOKEN.findall(t)
    if not tokens:
        return None, f"pas de nombre dans {text!r}"
    if len(tokens) > 1:
        return None, f"plusieurs nombres dans {text!r}"
    s = tokens[0]
    start = t.find(s)
    neg = t[:start].rstrip().endswith("-") or (t.startswith("(") and ")" in t[start:])
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        elif re.fullmatch(r"\d+,\d{1,2}", s):
            s = s.replace(",", ".")
        else:
            return None, f"virgule ambiguë dans {text!r}"
    elif s.count(".") > 1:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        else:
            return None, f"points ambigus dans {text!r}"
    try:
        v = float(s)
    except ValueError:
        return None, f"nombre illisible {text!r}"
    v = -v if neg else v
    return (int(v) if v == int(v) else v), None


def parse_quantity(text):
    m = re.fullmatch(r"[xX]?\s*(\d+(?:[.,]\d+)?)\s*[xX]?", text.strip())
    if not m:
        return None, f"quantité illisible {text!r}"
    v = float(m.group(1).replace(",", "."))
    return (int(v) if v == int(v) else v), None


def _iso(y, mo, d, raw):
    try:
        return dt.date(y, mo, d).isoformat(), None
    except ValueError:
        return None, f"date invalide {raw!r}"


MONTH_RE = (r"(?:janv|jan|f[eé]vr|feb|mars|mar|avr|apr|mai|may|juin|jun|juil|jul|"
            r"ao[uû]t|aug|sept|sep|oct|nov|d[eé]c|dec)[a-zéû]*")
SEP = r"[\s,.'’´`\-]*"
MONTH_TABLE = [("janv", 1), ("jan", 1), ("fév", 2), ("fev", 2), ("feb", 2), ("mars", 3),
               ("mar", 3), ("avr", 4), ("apr", 4), ("mai", 5), ("may", 5), ("juin", 6),
               ("jun", 6), ("juil", 7), ("jul", 7), ("août", 8), ("aout", 8), ("aug", 8),
               ("sept", 9), ("sep", 9), ("oct", 10), ("nov", 11), ("déc", 12), ("dec", 12)]


def month_num(tok):
    t = tok.lower()
    for prefix, n in MONTH_TABLE:
        if t.startswith(prefix):
            return n
    return None


def _year(ys):
    if len(ys) >= 4 and ys[:2] in ("19", "20"):
        return int(ys[:4])
    if len(ys) >= 2:
        return 2000 + int(ys[:2])  # règle : année à 2 chiffres -> 20YY
    return None


def parse_date(text):
    """Renvoie (iso, note). Si jour/mois est ambigu : (liste de 2 dates ISO, note)."""
    t = text.strip()
    m = re.search(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)", t)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)), text)
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d+)", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if y is None:
            return None, f"année illisible {text!r}"
        if a > 12 and b <= 12:
            return _iso(y, b, a, text)  # jour/mois
        if b > 12 and a <= 12:
            return _iso(y, a, b, text)  # mois/jour
        if a <= 12 and b <= 12:
            if a == b:
                return _iso(y, a, b, text)
            cands = [c for c in (_iso(y, a, b, text)[0], _iso(y, b, a, text)[0]) if c]
            if len(cands) == 2:
                return cands, f"date ambiguë (jour/mois) {text!r}"
            if cands:
                return cands[0], None
        return None, f"date invalide {text!r}"
    m = re.search(r"(?i)(" + MONTH_RE + r")\.?\s*(\d{1,2})" + SEP + r"(\d{4}|\d{2})(?!\d)", t)
    if m and month_num(m.group(1)) and _year(m.group(3)):
        return _iso(_year(m.group(3)), month_num(m.group(1)), int(m.group(2)), text)
    m = re.search(r"(?i)(\d{1,2})\s*-?\s*(" + MONTH_RE + r")\.?" + SEP + r"(\d{4}|\d{2})(?!\d)", t)
    if m and month_num(m.group(2)) and _year(m.group(3)):
        return _iso(_year(m.group(3)), month_num(m.group(2)), int(m.group(1)), text)
    return None, f"date non reconnue {text!r}"


def parse_time(text):
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?([AaPp][Mm])?", text)
    if not m:
        return None, f"heure non reconnue {text!r}"
    h, mi = int(m.group(1)), int(m.group(2))
    sec = int(m.group(3)) if m.group(3) else None
    ap = m.group(4)
    if ap:
        if not 1 <= h <= 12:
            return None, f"heure invalide {text!r}"
        h = h % 12 + (12 if ap.lower() == "pm" else 0)
    if h > 23 or mi > 59 or (sec is not None and sec > 59):
        return None, f"heure invalide {text!r}"
    out = f"{h:02d}:{mi:02d}"
    return (out + f":{sec:02d}" if sec is not None else out), None


def parse_phone(text):
    if re.search(r"[A-Za-z]{3,}", re.sub(r"(?i)tel|phone|fax|ph", "", text)):
        return None, f"téléphone avec lettres {text!r}"
    digits = re.sub(r"[^\d+]", "", text)
    digits = ("+" if digits.startswith("+") else "") + digits.replace("+", "")
    if re.fullmatch(r"\+?\d{6,15}", digits):
        return digits, None
    return None, f"téléphone invalide {text!r}"


def parse_text(text):
    return (text or None), None


PARSERS = {
    "merchant.name": parse_text,
    "merchant.phone": parse_phone,
    "date": parse_date,
    "time": parse_time,
    "amounts.subtotal": parse_amount,
    "amounts.tax": parse_amount,
    "amounts.tip": parse_amount,
    "amounts.total": parse_amount,
}


def same(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return re.sub(r"[^0-9a-z]", "", a.lower()) == re.sub(r"[^0-9a-z]", "", b.lower())
    return a == b


# --------------------------------------------------------------------------
# Articles : association description / quantité / prix par position verticale
# --------------------------------------------------------------------------
def align(descs, cands, prefer_right):
    """Appariement monotone description -> zone : l'ordre vertical est conservé et
    le décalage moyen (photo inclinée) est compensé. Renvoie {index_desc: index_zone}."""
    n, m = len(descs), len(cands)
    if not n or not m:
        return {}
    cs = sorted(range(m), key=lambda j: (cands[j]["cy"], cands[j]["cx"]))
    dys = []
    for d in descs:
        near = [c["cy"] - d["cy"] for c in cands
                if abs(c["cy"] - d["cy"]) <= 1.5 * max(d["h"], c["h"], 1.0)]
        if near:
            dys.append(min(near, key=abs))
    off = statistics.median(dys) if dys else 0.0
    score = [[(0, 0.0)] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d, c = descs[i - 1], cands[cs[j - 1]]
            best, b = score[i - 1][j], (i - 1, j, False)
            if score[i][j - 1] > best:
                best, b = score[i][j - 1], (i, j - 1, False)
            dy = c["cy"] - d["cy"] - off
            if abs(dy) <= 0.8 * max(d["h"], c["h"], 1.0):
                cost = abs(dy) + 1e-6 * (-c["cx"] if prefer_right else c["cx"])
                cand = (score[i - 1][j - 1][0] + 1, score[i - 1][j - 1][1] - cost)
                if cand > best:
                    best, b = cand, (i - 1, j - 1, True)
            score[i][j], back[i][j] = best, b
    pairs, i, j = {}, n, m
    while i > 0 and j > 0:
        pi, pj, matched = back[i][j]
        if matched:
            pairs[i - 1] = cs[j - 1]
        i, j = pi, pj
    return pairs


def match_items(zones, notes, stats):
    descs = sorted((z for z in zones if z["label"] == ITEM_DESC),
                   key=lambda z: (z["cy"], z["cx"]))
    items = [{"description": d["text"] or None, "quantity": None, "price": None}
             for d in descs]

    def assign(label, key, parse, prefer_right):
        cands = [z for z in zones if z["label"] == label]
        pairs = align(descs, cands, prefer_right)
        for i, j in pairs.items():
            v, note = parse(cands[j]["text"])
            items[i][key] = v
            if note:
                notes.append(f"items[{i}].{key}: {note}")
        return len(cands), len(cands) - len(pairs)

    nq, uq = assign(ITEM_QTY, "quantity", parse_quantity, prefer_right=False)
    npr, up = assign(ITEM_PRICE, "price", parse_amount, prefer_right=True)
    if uq:
        notes.append(f"items: {uq} quantité(s) non associée(s)")
    if up:
        notes.append(f"items: {up} prix non associé(s)")
    stats["items"] += len(items)
    stats["items_with_price"] += sum(1 for it in items if it["price"] is not None)
    stats["items_with_quantity"] += sum(1 for it in items if it["quantity"] is not None)
    stats["price_zones"] += npr
    stats["price_zones_unassigned"] += up
    stats["quantity_zones"] += nq
    stats["quantity_zones_unassigned"] += uq
    return items


# --------------------------------------------------------------------------
# Conversion d'un reçu
# --------------------------------------------------------------------------
def convert(record, mapping, split, stats):
    zones = [make_zone(a) for a in record["annotations"]]
    ordered = sorted(zones, key=lambda z: (z["cy"], z["cx"]))
    by_field = defaultdict(list)
    for z in ordered:
        info = mapping.get(str(z["label"]), {})
        if info.get("role") == "value" and not info["field"].startswith("items["):
            by_field[info["field"]].append(z)

    notes, alternatives, raw = [], {}, {}
    out = {
        "merchant": {"name": None, "address": None, "phone": None},
        "date": None, "time": None,
        "amounts": {"subtotal": None, "tax": None, "tip": None, "total": None},
    }

    def put(path, value):
        parts = path.split(".")
        node = out
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value

    for field, zs in by_field.items():
        texts = [z["text"] for z in zs]
        raw[field] = texts
        stats[f"{field}:present"] += 1
        if field == "merchant.address":  # policy join
            joined = " ".join(t for t in texts if t)
            put(field, joined or None)
            stats[f"{field}:parsed"] += 1 if joined else 0
            continue
        valid, ambiguous, last_note = [], [], None
        for t in texts:  # policy any_of
            v, note = PARSERS[field](t)
            if isinstance(v, list):  # date jour/mois ambiguë : 2 candidats
                ambiguous.extend(x for x in v if x not in ambiguous)
                last_note = note
            elif v is None:
                last_note = note
            elif not any(same(v, x) for x in valid):
                valid.append(v)
        if valid:
            put(field, valid[0])
            stats[f"{field}:parsed"] += 1
            if len(valid) > 1:
                alternatives[field] = valid[1:]
        elif ambiguous:
            # valeur laissée à null : la référence n'est pas connue, on garde les 2 lectures possibles
            alternatives[field] = ambiguous
            stats[f"{field}:ambiguous"] += 1
            notes.append(f"{field}: {last_note} -> value=null, voir alternatives")
        else:
            notes.append(f"{field}: {last_note}")

    items = match_items(zones, notes, stats)
    stats["receipts"] += 1
    return {
        "meta": {
            "file": record["file_name"], "source": "wildreceipt", "split": split,
            "language": None, "quality": None, "verified": False, "notes": "",
            "conversion_notes": notes,
        },
        "document_type": "receipt",
        **out,
        "items": items,
        "alternatives": alternatives,
        "raw": raw,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mapping = json.load(open(args.mapping, encoding="utf-8"))["classes"]
    stats = Counter()
    with open(args.input, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            if line.strip():
                res = convert(json.loads(line), mapping, args.split, stats)
                fout.write(json.dumps(res, ensure_ascii=False) + "\n")

    print(f"{stats['receipts']} reçus -> {args.out}")
    for f in ["merchant.name", "merchant.address", "merchant.phone", "date", "time",
              "amounts.subtotal", "amounts.tax", "amounts.tip", "amounts.total"]:
        p, ok, am = stats[f"{f}:present"], stats[f"{f}:parsed"], stats[f"{f}:ambiguous"]
        extra = f", ambigu dans {am:4}" if am else ""
        print(f"  {f:18} annoté dans {p:4} reçus, converti proprement dans {ok:4}{extra}")
    print(f"  articles: {stats['items']} | avec prix: {stats['items_with_price']} | "
          f"avec quantité: {stats['items_with_quantity']}")
    print(f"  zones prix non associées: {stats['price_zones_unassigned']}/{stats['price_zones']} | "
          f"zones quantité non associées: {stats['quantity_zones_unassigned']}/{stats['quantity_zones']}")


if __name__ == "__main__":
    main()
