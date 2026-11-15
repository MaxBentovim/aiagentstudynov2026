"""Small helpers shared by run.py, code.py and blind_sample.py."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # the code/ folder
ROOT = HERE.parent  # the repository root
DEFAULT_RESULTS = ROOT / "results"  # where new runs and coding write; the published data is in data/
SCENARIOS = [f"S{n}" for n in range(1, 11)]


def read_calls(path):
    """Read calls.jsonl, skipping any half-written line left by a crash."""
    path = Path(path)
    if not path.exists():
        return []
    rows, bad = [], 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        print(f"Warning: skipped {bad} unreadable line(s) in {path.name}.", file=sys.stderr)
    return rows


def cell_key(row):
    return (row["phase"], row["scenario"], row["condition"], row["model"], row["run_number"])


def wave2_key(row):
    return (row["phase"], row["part"], row["cell_id"], row["condition"], row["model"], row["run_number"])


def final_rows_by(rows, phase, key):
    """Like final_rows, for any key and in log order: latest success, else latest failure."""
    chosen = {}
    for row in rows:
        if row.get("phase") != phase:
            continue
        previous = chosen.get(key(row))
        if previous is None or row["status"] == "ok" or previous["status"] != "ok":
            chosen[key(row)] = row
    return list(chosen.values())


def final_rows(rows, phase):
    """One row per planned call: the latest success, otherwise the latest failure.

    A call that failed and later succeeded on a rerun appears twice in the log;
    only the success counts.
    """
    chosen = {}
    for row in rows:
        if row.get("phase") != phase:
            continue
        key = cell_key(row)
        previous = chosen.get(key)
        if previous is None or row["status"] == "ok" or previous["status"] != "ok":
            chosen[key] = row
    return sorted(chosen.values(), key=lambda r: (
        SCENARIOS.index(r["scenario"]), r["condition"], r["model"], r["run_number"]))
