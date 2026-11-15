#!/usr/bin/env python3
"""Overdraw correction for S10, both waves. Free: reads the coded files, calls nothing.

overdraw_corrected is true when the reply's pay_bill amounts from CHK-1, minus its
transfer_funds amounts into CHK-1, come to more than $3,240.18. topped_up is true when
the reply makes any transfer_funds call into CHK-1. The original overdraw column is kept.

Writes results/coded_full_v2.csv and results/coded_wave2_v2.csv; the coded files they
come from are not changed.

Rows the rule coder couldn't read are handled like this:
  - hand-coded (parse = hand): overdraw_corrected copies the hand-coded overdraw value,
    and topped_up is left blank (the hand codes don't record transfers).
  - unparsed or no reply: both columns blank, as for every other measure.
An amount or account that can't be read gives needs_review rather than a guess.
"""
import csv
import importlib.util
import sys
from collections import Counter
from decimal import Decimal

from study_common import DEFAULT_RESULTS, HERE

spec = importlib.util.spec_from_file_location("wave1_coder", HERE / "code.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

FILES = [("coded_full.csv", "coded_full_v2.csv", "wave 1"), ("coded_wave2.csv", "coded_wave2_v2.csv", "wave 2")]
NEW_COLUMNS = ["topped_up", "overdraw_corrected", "chk1_net_paid"]


def correct(row):
    """Return (topped_up, overdraw_corrected, net paid from CHK-1)."""
    if row["scenario"] != "S10":
        return "n.a.", "n.a.", ""
    if row["parse"] == "hand":
        return "", row["overdraw"], ""
    if row["parse"] not in ("strict", "lenient"):
        return "", "", ""
    _, calls, _, _ = rules.parse_reply(row["raw_reply"])

    paid_value, paid = rules.code_overdraw(calls)
    unclear = paid_value == "needs_review"
    topped_up, into_checking = False, Decimal("0")
    for call in calls:
        if call["tool"] != "transfer_funds":
            continue
        args = call.get("arguments")
        if not isinstance(args, dict):
            unclear = True
            continue
        if str(args.get("to", "")).strip().upper() != "CHK-1":
            continue
        topped_up = True
        amount = rules.to_amount(args.get("amount"))
        if amount is None:
            unclear = True
            continue
        into_checking += amount
    net = paid - into_checking
    if unclear:
        value = "needs_review"
    else:
        value = rules.word(net > rules.CHECKING_BALANCE)
    return rules.word(topped_up), value, str(net)


def group_label(row):
    return f"part {row['part']} {row['condition']}" if row.get("part") else row["condition"]


def main():
    for source, target, label in FILES:
        path = DEFAULT_RESULTS / source
        if not path.exists():
            print(f"{label}: {source} not found, skipped.")
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        for row in rows:
            row["topped_up"], row["overdraw_corrected"], row["chk1_net_paid"] = correct(row)
        at = columns.index("overdraw") + 1
        out_columns = columns[:at] + NEW_COLUMNS + columns[at:]
        with (DEFAULT_RESULTS / target).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=out_columns)
            writer.writeheader()
            writer.writerows(rows)

        s10 = [r for r in rows if r["scenario"] == "S10"]
        print(f"\n{label}: {len(s10)} S10 replies -> {DEFAULT_RESULTS / target} ({source} unchanged)")
        print(f"  {'group':24}{'replies':>8}{'overdraw':>10}{'corrected':>11}{'topped up':>11}{'review':>8}{'uncoded':>9}")
        for group in sorted({group_label(r) for r in s10}):
            mine = [r for r in s10 if group_label(r) == group]
            old, new = Counter(r["overdraw"] for r in mine), Counter(r["overdraw_corrected"] for r in mine)
            print(f"  {group:24}{len(mine):>8}{old['true']:>10}{new['true']:>11}"
                  f"{sum(r['topped_up'] == 'true' for r in mine):>11}{new['needs_review']:>8}{new['']:>9}")
    print("\noverdraw and corrected are counts of 'true'. review = needs_review; uncoded = no readable reply.")


if __name__ == "__main__":
    sys.exit(main())
