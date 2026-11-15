#!/usr/bin/env python3
"""Put every reply the coder couldn't parse into a file for hand-coding.

Run code.py first. Writes results/unparsed_handcode.csv (open this one) and
results/unparsed_key.csv (don't open it until the hand-coding is finished).

Condition is hidden behind an ID and the order is shuffled with a fixed seed. Calls
that failed outright have no reply to read and are left out.
"""
import argparse
import csv
import random
import sys
from pathlib import Path

from blind_sample import HAND_COLUMNS, SEED
from study_common import DEFAULT_RESULTS, final_rows, read_calls


def main():
    parser = argparse.ArgumentParser(description="Collect unparsed replies for hand-coding.")
    parser.add_argument("--phase", choices=["full", "pilot"], default="full")
    parser.add_argument("--input", type=Path, default=DEFAULT_RESULTS / "calls.jsonl")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()

    coded_path = args.outdir / f"coded_{args.phase}.csv"
    if not coded_path.exists():
        sys.exit(f"{coded_path} not found. Run code.py first.")
    with coded_path.open(newline="", encoding="utf-8") as handle:
        unparsed = {r["run_id"] for r in csv.DictReader(handle)
                    if r["parse"] == "failed" and r["call_status"] == "ok"}

    rows = [r for r in final_rows(read_calls(args.input), args.phase) if r["run_id"] in unparsed]
    if not rows:
        sys.exit("No unparsed replies found.")
    random.Random(SEED).shuffle(rows)

    sheet_path, key_path = args.outdir / "unparsed_handcode.csv", args.outdir / "unparsed_key.csv"
    with sheet_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["blind_id", "scenario", "user_message", "model_reply",
                         "hand_action_status", *HAND_COLUMNS, "hand_notes"])
        for number, row in enumerate(rows, start=1):
            scenario = row["scenario"]
            writer.writerow([f"U{number:03d}", scenario, row["user_message"], row["response_text"], "",
                             *("" if scenario in applies else "n.a." for applies in HAND_COLUMNS.values()), ""])
    with key_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["blind_id", "run_id", "scenario", "condition", "model", "provider", "run_number"])
        for number, row in enumerate(rows, start=1):
            writer.writerow([f"U{number:03d}", row["run_id"], row["scenario"], row["condition"],
                             row["model"], row["provider"], row["run_number"]])

    print(f"{len(rows)} unparsed replies. Hand-code: {sheet_path}")
    print(f"Keep closed until you finish: {key_path}")


if __name__ == "__main__":
    main()
