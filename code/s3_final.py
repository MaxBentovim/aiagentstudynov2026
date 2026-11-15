#!/usr/bin/env python3
"""Final S3 memo labels and table. Free: reads existing files, calls nothing.

Each full-run S3 reply gets one final label: your hand code if you coded it (wave 1 blind
sample, wave 2 S3 sample or flagged review), otherwise the 3-coder majority from
s3_coding.csv. If two hand codes for the same reply disagree, the script stops and lists them.

Writes:
  results/s3_final.csv        one row per reply: final label, where it came from, and all codes
  results/s3_final_table.csv  counts per category by wave, part and condition, with the share
                              that acted or offered/asked and its 95% Wilson interval
"""
import csv
import json
import math
import sys
from collections import Counter

from study_common import DEFAULT_RESULTS

R = DEFAULT_RESULTS
LABELS = ["acted", "offered_or_asked", "neutral", "flagged_suspicious", "not_mentioned"]
RISKY = {"acted", "offered_or_asked"}
HAND_SHEETS = [("blind_sample.csv", "blind_key.csv", "blind_id"),
               ("blind_sample_wave2_s3.csv", "blind_key_wave2_s3.csv", "blind_id"),
               ("s3_review.csv", "s3_review_key.csv", "review_id")]
CONDITION_ORDER = ["bare", "duty", "confirm_only", "full_rules", "policy"]


def read(name):
    with (R / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def norm(value):
    return (value or "").strip().lower().replace(" ", "_")


def wilson(k, n, z=1.96):
    if n == 0:
        return "", ""
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


def main():
    coding = {r["run_id"]: r for r in read("s3_coding.csv")}
    meta = {}
    for name in ("calls.jsonl", "calls_wave2.jsonl"):
        for line in (R / name).open(encoding="utf-8"):
            row = json.loads(line)
            if row["run_id"] in coding:
                meta[row["run_id"]] = row

    hand, problems = {}, []
    for sheet, key_name, id_col in HAND_SHEETS:
        if not (R / sheet).exists():
            continue
        key = {r[id_col]: r for r in read(key_name)}
        for row in read(sheet):
            if row.get("scenario") != "S3":
                continue
            label = norm(row.get("hand_s3_category"))
            if label not in LABELS:
                problems.append(f"{sheet} {row[id_col]}: '{row.get('hand_s3_category')}' isn't a category")
                continue
            run_id = key[row[id_col]]["run_id"]
            if run_id in hand and hand[run_id][0] != label:
                problems.append(f"{run_id}: {hand[run_id][1]} says {hand[run_id][0]}, {sheet} {row[id_col]} says {label}")
            hand.setdefault(run_id, (label, f"{sheet} {row[id_col]}"))
    if problems:
        sys.exit("Hand codes need fixing first:\n  " + "\n  ".join(problems))

    final = []
    for run_id, c in coding.items():
        m = meta[run_id]
        if run_id in hand:
            label, source = hand[run_id][0], "hand"
        elif c["majority"]:
            label, source = c["majority"], "majority"
        else:
            label, source = "", "none"
        final.append({"run_id": run_id, "wave": c["wave"], "part": m.get("part", ""), "cell_id": m.get("cell_id", ""),
                      "condition": m["condition"], "wording": m.get("wording", ""), "model": m["model"],
                      "final_label": label, "source": source, "hand_label": hand.get(run_id, ("", ""))[0],
                      "majority": c["majority"], "metis_label": c["metis_label"],
                      "deepseek_label": c["deepseek_label"], "gptoss_label": c["gptoss_label"]})
    with (R / "s3_final.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(final[0]))
        writer.writeheader()
        writer.writerows(final)

    def group_rows():
        groups = {}
        for r in final:
            groups.setdefault((f"wave {r['wave']}", "all" if r["wave"] == "1" else f"Part {r['part']}", r["condition"]), []).append(r)
            if r["wave"] == "2":
                groups.setdefault(("wave 2", "B+C", r["condition"]), []).append(r)
        order = {"all": 0, "Part B": 1, "Part C": 2, "B+C": 3}
        return sorted(groups.items(), key=lambda kv: (kv[0][0], order[kv[0][1]], CONDITION_ORDER.index(kv[0][2])))

    table = []
    for (wave, part, condition), rows in group_rows():
        counts = Counter(r["final_label"] for r in rows)
        n = sum(counts[l] for l in LABELS)
        risky = counts["acted"] + counts["offered_or_asked"]
        low, high = wilson(risky, n)
        # Uncertainty: the same share using the models alone (no hand codes; replies without a
        # majority left out), and counting a reply if any coder, models or you, said acted or offered.
        with_majority = [r for r in rows if r["majority"]]
        model_risky = sum(r["majority"] in RISKY for r in with_majority)
        model_low, model_high = wilson(model_risky, len(with_majority))
        any_risky = sum(any(r[c] in RISKY for c in ("metis_label", "deepseek_label", "gptoss_label", "hand_label"))
                        for r in rows)
        any_low, any_high = wilson(any_risky, len(rows))
        table.append({"wave": wave, "part": part, "condition": condition, "replies": n,
                      **{l: counts[l] for l in LABELS},
                      "acted_or_offered_rate": round(risky / n, 3) if n else "", "ci95_low": low, "ci95_high": high,
                      "models_only_n": len(with_majority), "models_only_acted_or_offered": model_risky,
                      "models_only_rate": round(model_risky / len(with_majority), 3) if with_majority else "",
                      "models_only_ci95_low": model_low, "models_only_ci95_high": model_high,
                      "any_coder_acted_or_offered": any_risky,
                      "any_coder_rate": round(any_risky / len(rows), 3) if rows else "",
                      "any_coder_ci95_low": any_low, "any_coder_ci95_high": any_high,
                      "flagged_rate": round(counts["flagged_suspicious"] / n, 3) if n else "",
                      "hand_coded": sum(r["source"] == "hand" for r in rows)})
    with (R / "s3_final_table.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    sources = Counter(r["source"] for r in final)
    print(f"{len(final)} S3 replies: {sources['hand']} hand-coded, {sources['majority']} from the 3-coder majority"
          + (f", {sources['none']} with no label" if sources["none"] else "") + ".")
    print(f"Wrote {R / 's3_final.csv'} and {R / 's3_final_table.csv'}\n")
    print("Share that acted or offered/asked, [95% CI]:")
    print(f"{'wave':7}{'part':8}{'condition':14}{'n':>4}   {'final':22}{'models only':26}{'any coder':22}")
    for t in table:
        final_s = f"{t['acted_or_offered_rate']:.0%} [{t['ci95_low']:.0%}-{t['ci95_high']:.0%}]"
        model_s = (f"{t['models_only_rate']:.0%} [{t['models_only_ci95_low']:.0%}-{t['models_only_ci95_high']:.0%}]"
                   + (f" n={t['models_only_n']}" if t["models_only_n"] != t["replies"] else ""))
        any_s = f"{t['any_coder_rate']:.0%} [{t['any_coder_ci95_low']:.0%}-{t['any_coder_ci95_high']:.0%}]"
        print(f"{t['wave']:7}{t['part']:8}{t['condition']:14}{t['replies']:>4}   {final_s:22}{model_s:26}{any_s:22}")


if __name__ == "__main__":
    main()
