"""Part 1: statistics over cleaned records."""

from collections import Counter, defaultdict


def _avg(values):
    return round(sum(values) / len(values), 2) if values else None


def build_statistics(valid):
    by_month = Counter(r["date"][:7] for r in valid)
    by_channel = Counter(r["channel"] for r in valid)

    by_month_channel = defaultdict(Counter)
    for r in valid:
        by_month_channel[r["date"][:7]][r["channel"]] += 1

    # Amounts in different currencies cannot be averaged together before
    # conversion (Part 2), so the average is computed per currency.
    amounts = defaultdict(list)
    for r in valid:
        amounts[r["currency"]].append(r["amount"])

    average_amount = {}
    for cur in sorted(amounts):
        vals = amounts[cur]
        nonzero = [v for v in vals if v > 0]
        average_amount[cur] = {
            "count": len(vals),
            "average": _avg(vals),
            "count_nonzero": len(nonzero),
            "average_nonzero": _avg(nonzero),
        }

    return {
        "requests_by_month": dict(sorted(by_month.items())),
        "requests_by_channel": dict(sorted(by_channel.items())),
        "requests_by_month_and_channel": {
            m: dict(sorted(c.items())) for m, c in sorted(by_month_channel.items())
        },
        "average_amount_by_currency": average_amount,
    }



def build_gel_statistics(records):
    """Statistics after Part 2 conversion (amount_gel)."""
    sources = Counter(r["rate_source"] for r in records)
    gel = [r["amount_gel"] for r in records if r["amount_gel"] is not None]
    nonzero = [v for v in gel if v > 0]
    return {
        "conversion": {
            "converted_records": len(gel),
            "not_converted_records": len(records) - len(gel),
            "rate_source_counts": dict(sorted(sources.items())),
        },
        "average_amount_gel": _avg(gel),
        "average_amount_gel_nonzero": _avg(nonzero),
        "total_amount_gel": round(sum(gel), 2),
    }


def build_category_statistics(records):
    """Part 3: number of requests per LLM category."""
    counts = Counter(r["category"] or "unclassified" for r in records)
    return {"requests_by_category": dict(counts.most_common())}
