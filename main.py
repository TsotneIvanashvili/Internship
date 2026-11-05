"""Entry point: python main.py [input.json]"""

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.analysis import build_category_statistics, build_gel_statistics, build_statistics
from src.classifier import classify_records
from src.cleaning import clean_records
from src.currency import SOURCE_CURRENT, SOURCE_UNAVAILABLE, convert_records

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
CACHE_PATH = BASE_DIR / "cache" / "classifications.json"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of records")
    return data


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    load_dotenv(BASE_DIR / ".env")  # GEMINI_API_KEY
    # Windows console defaults to cp1252 and cannot print Georgian text.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "requests.json"
    records = load_json(input_path)

    # Part 1: cleaning + statistics
    valid, rejected, corrections = clean_records(records)
    summary = {
        "total_records": len(records),
        "valid_records": len(valid),
        "rejected_records": len(rejected),
        "corrections": corrections,
        **build_statistics(valid),
    }

    # Part 2: conversion to GEL (NBG API)
    convert_records(valid)
    summary.update(build_gel_statistics(valid))

    # Part 3: classification with an LLM (Gemini)
    classify_records(valid, CACHE_PATH)
    summary.update(build_category_statistics(valid))

    save_json(valid, OUTPUT_DIR / "processed.json")
    save_json(rejected, OUTPUT_DIR / "rejected.json")
    save_json(summary, OUTPUT_DIR / "summary.json")

    print(f"Records: {len(records)} | valid: {len(valid)} | "
          f"rejected: {len(rejected)} | corrected fields: {len(corrections)}")
    for item in rejected:
        rid = item["record"].get("id") if isinstance(item["record"], dict) else "?"
        print(f"  rejected {rid}: {len(item['reasons'])} reason(s)")
    sources = summary["conversion"]["rate_source_counts"]
    print(f"Conversion: current-rate fallback: {sources.get(SOURCE_CURRENT, 0)} | "
          f"unavailable: {sources.get(SOURCE_UNAVAILABLE, 0)}")
    print(f"Categories: {summary['requests_by_category']}")
    print(f"Output written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
