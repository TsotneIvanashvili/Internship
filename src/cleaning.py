"""Part 1: validation and cleaning of customer requests.

Every record goes through the same checks. Fixable problems (date format,
currency spelling, amount written as text) are corrected and logged.
Records that cannot be fixed are rejected with a list of reasons.
"""

import re
from datetime import date

VALID_CHANNELS = {"web", "email", "call"}
VALID_CURRENCIES = {"GEL", "USD", "EUR"}

# Symbols / words that unambiguously identify a currency.
CURRENCY_ALIASES = {
    "GEL": "GEL", "LARI": "GEL", "ლარი": "GEL", "₾": "GEL",
    "USD": "USD", "$": "USD", "DOLLAR": "USD", "დოლარი": "USD",
    "EUR": "EUR", "€": "EUR", "EURO": "EUR", "ევრო": "EUR",
}

GEORGIAN_MONTHS = {
    "იანვარი": 1, "თებერვალი": 2, "მარტი": 3, "აპრილი": 4,
    "მაისი": 5, "ივნისი": 6, "ივლისი": 7, "აგვისტო": 8,
    "სექტემბერი": 9, "ოქტომბერი": 10, "ნოემბერი": 11, "დეკემბერი": 12,
}


class FieldError(ValueError):
    """Raised when a field value is invalid and cannot be fixed."""


# ---------------------------------------------------------------- date

def parse_date(value):
    """Return (iso_date, was_fixed). Raise FieldError if impossible."""
    if value is None or str(value).strip() == "":
        raise FieldError("თარიღი არ არის მითითებული")
    raw = str(value).strip()

    # 1) Expected format YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        y, mo, d = map(int, m.groups())
        return _build_date(y, mo, d, raw), raw != _iso(y, mo, d)

    # 2) YYYY.MM.DD or YYYY/MM/DD (year first -> month, day order is standard)
    m = re.fullmatch(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", raw)
    if m:
        y, mo, d = map(int, m.groups())
        return _build_date(y, mo, d, raw), True

    # 3) DD/MM/YYYY or DD.MM.YYYY (day first: format used in Georgia)
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if m:
        d, mo, y = map(int, m.groups())
        return _build_date(y, mo, d, raw), True

    # 4) "5 მაისი 2026"
    m = re.fullmatch(r"(\d{1,2})\s+(\S+)\s+(\d{4})", raw)
    if m and m.group(2) in GEORGIAN_MONTHS:
        d, y = int(m.group(1)), int(m.group(3))
        return _build_date(y, GEORGIAN_MONTHS[m.group(2)], d, raw), True

    raise FieldError(f"თარიღის ფორმატი ამოუცნობია: '{raw}'")


def _build_date(y, mo, d, raw):
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise FieldError(f"არარსებული თარიღი: '{raw}'") from None


def _iso(y, mo, d):
    return f"{y:04d}-{mo:02d}-{d:02d}"


# -------------------------------------------------------------- amount

def parse_amount(value):
    """Return (amount, currency_hint, was_fixed).

    currency_hint is a currency found inside a text amount ("350 ლარი"),
    otherwise None.
    """
    if value is None:
        raise FieldError("თანხა არ არის მითითებული")
    if isinstance(value, bool):  # bool is a subclass of int in Python
        raise FieldError(f"თანხა არ არის რიცხვი: {value!r}")
    if isinstance(value, (int, float)):
        amount = float(value)
        fixed = False
        hint = None
    else:
        amount, hint = _parse_amount_text(str(value))
        fixed = True

    if amount < 0:
        raise FieldError(f"თანხა უარყოფითია: {amount:g}")
    return amount, hint, fixed


def _parse_amount_text(raw):
    text = raw.strip()
    hint = None
    for alias, code in CURRENCY_ALIASES.items():
        if alias.lower() in text.lower():
            hint = code
            text = re.sub(re.escape(alias), "", text, flags=re.IGNORECASE)
            break

    # Drop spaces used as thousand separators (incl. non-breaking space).
    text = re.sub(r"[\s ]", "", text)
    if "," in text and "." in text:
        text = text.replace(",", "")          # 1,234.50 -> 1234.50
    elif "," in text:
        text = text.replace(",", ".")         # 3200,00 -> 3200.00

    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise FieldError(f"თანხა ვერ გადაიქცა რიცხვად: '{raw}'")
    return float(text), hint


# ------------------------------------------------------------ currency

def parse_currency(value, hint=None):
    """Return (currency_code, was_fixed)."""
    if value is None or str(value).strip() == "":
        if hint:
            return hint, True
        raise FieldError("ვალუტა არ არის მითითებული")

    raw = str(value).strip()
    code = CURRENCY_ALIASES.get(raw.upper(), CURRENCY_ALIASES.get(raw))
    if code is None:
        raise FieldError(f"უცნობი ვალუტა: '{raw}'")
    if hint and hint != code:
        raise FieldError(
            f"ვალუტა ეწინააღმდეგება თანხაში მითითებულს: '{raw}' vs {hint}")
    return code, code != raw


# --------------------------------------------------------------- other

def parse_channel(value):
    if value is None:
        raise FieldError("არხი არ არის მითითებული")
    channel = str(value).strip().lower()
    if channel not in VALID_CHANNELS:
        raise FieldError(f"უცნობი არხი: '{value}'")
    return channel, channel != value


def parse_text(value):
    if value is None or str(value).strip() == "":
        raise FieldError("მიმართვის ტექსტი ცარიელია")
    text = " ".join(str(value).split())  # collapse extra whitespace
    return text, text != value


# ---------------------------------------------------------------- main

def clean_records(records):
    """Validate all records.

    Returns (valid, rejected, corrections):
      valid       - list of cleaned records
      rejected    - list of {"record": original, "reasons": [...]}
      corrections - list of {"id", "field", "from", "to"}
    """
    valid, rejected, corrections = [], [], []
    seen = {}  # id -> original record

    for original in records:
        if not isinstance(original, dict):
            rejected.append({"record": original,
                             "reasons": ["ჩანაწერი არ არის ობიექტი"]})
            continue

        reasons = []
        rec_id = original.get("id")
        rec_id = str(rec_id).strip() if rec_id is not None else ""

        if not rec_id:
            reasons.append("id არ არის მითითებული")
        elif rec_id in seen:
            if seen[rec_id] == original:
                reasons.append(f"დუბლიკატი: {rec_id} უკვე არსებობს (იდენტური ჩანაწერი)")
            else:
                reasons.append(f"id {rec_id} მეორდება განსხვავებული შინაარსით")

        cleaned = {"id": rec_id}
        fixes = []

        def check(field, func, *args):
            try:
                result = func(original.get(field), *args)
            except FieldError as e:
                reasons.append(str(e))
                return None
            value, was_fixed = result[0], result[-1]
            cleaned[field] = value
            if was_fixed:
                fixes.append({"id": rec_id, "field": field,
                              "from": original.get(field), "to": value})
            return result

        check("date", parse_date)
        check("channel", parse_channel)
        check("text", parse_text)
        amount_res = check("amount", parse_amount)
        hint = amount_res[1] if amount_res else None
        check("currency", parse_currency, hint)

        if rec_id and rec_id not in seen:
            seen[rec_id] = original

        if reasons:
            rejected.append({"record": original, "reasons": reasons})
        else:
            valid.append(cleaned)
            corrections.extend(fixes)

    return valid, rejected, corrections
