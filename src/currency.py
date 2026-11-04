"""Part 2: conversion of USD/EUR amounts to GEL via the National Bank of
Georgia (NBG) public API.

Endpoint:
    GET https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date=YYYY-MM-DD

Response:
    [{"date": "...", "currencies": [
        {"code": "USD", "quantity": 1, "rate": 2.6902, ...}, ...]}]

Notes found while testing:
  * "currencies=USD,EUR" returns an empty list.
  * "currencies=USD&currencies=EUR" works with "date", but WITHOUT "date"
    it also returns an empty list (a single currency works).
  * So the "currencies" filter is not used at all: one request returns
    all ~40 currencies for the date and USD/EUR are picked locally.
  * Without "date" the API returns the current rate.
  * "rate" is the price of "quantity" units (e.g. 1000 AMD), so the
    rate per one unit is rate / quantity.
"""

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

NBG_URL = os.environ.get(
    "NBG_API_URL",
    "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/",
)
FOREIGN_CURRENCIES = ("USD", "EUR")

SOURCE_GEL = "gel"                    # no conversion needed
SOURCE_REQUEST_DATE = "nbg_request_date"
SOURCE_CURRENT = "nbg_current"        # fallback: today's rate
SOURCE_UNAVAILABLE = "unavailable"    # API failed completely


class NbgApiError(Exception):
    """The API did not return a usable answer."""


class NbgRateClient:
    def __init__(self, timeout=10, retries=3, backoff=1.0):
        self.session = requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        # date ("YYYY-MM-DD" or None for current) -> {code: rate} or None
        self._cache = {}

    # -------------------------------------------------------------- HTTP

    def _fetch(self, day):
        """Return {code: rate_per_unit} for USD and EUR on `day`."""
        params = {"date": day} if day else {}

        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(NBG_URL, params=params, timeout=self.timeout)
                if 400 <= resp.status_code < 500:
                    # Client error: retrying will not help.
                    raise NbgApiError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return self._parse(resp.json())
            except NbgApiError:
                raise
            except (requests.RequestException, ValueError) as e:
                # Timeout, connection error, 5xx, invalid JSON.
                last_error = e
                log.warning("NBG API attempt %d/%d failed (%s): %s",
                            attempt, self.retries, day or "current", e)
                if attempt < self.retries:
                    time.sleep(self.backoff * attempt)
        raise NbgApiError(str(last_error))

    @staticmethod
    def _parse(data):
        if not isinstance(data, list) or not data:
            raise NbgApiError("empty response")
        rates = {}
        for item in data[0].get("currencies", []):
            if item.get("code") not in FOREIGN_CURRENCIES:
                continue
            try:
                rates[item["code"]] = float(item["rate"]) / float(item["quantity"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
        if not rates:
            raise NbgApiError("no rates in response")
        return rates

    def _rates_for(self, day):
        if day not in self._cache:
            try:
                self._cache[day] = self._fetch(day)
            except NbgApiError as e:
                log.warning("NBG rates unavailable for %s: %s", day or "current", e)
                self._cache[day] = None  # remember failure, don't retry per record
        return self._cache[day]

    # ------------------------------------------------------------ public

    def get_rate(self, currency, day):
        """Return (rate, source). rate is None if no rate could be found."""
        if currency == "GEL":
            return 1.0, SOURCE_GEL

        rates = self._rates_for(day)
        if rates and currency in rates:
            return rates[currency], SOURCE_REQUEST_DATE

        rates = self._rates_for(None)  # fallback: current rate
        if rates and currency in rates:
            return rates[currency], SOURCE_CURRENT

        return None, SOURCE_UNAVAILABLE


def convert_records(records, client=None):
    """Add amount_gel, rate and rate_source to every record (in place)."""
    client = client or NbgRateClient()
    for r in records:
        rate, source = client.get_rate(r["currency"], r["date"])
        r["rate"] = round(rate, 4) if rate is not None else None
        r["amount_gel"] = round(r["amount"] * rate, 2) if rate is not None else None
        r["rate_source"] = source
    return records
