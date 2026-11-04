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

