#!/usr/bin/env python3
"""Wave 2 batch runner. See README.md.

  --dry-run-wave2   print the A-NEW-5000 (duty) and C-S4-W2 (full_rules) prompts; calls nothing
  --wave2-pilot     112 calls (spends budget)
  --wave2-full      3,440 calls, asks first (spends budget)

Same endpoint, Keychain key and request settings as run.py (wave 1). Logs to
results/calls_wave2.jsonl, so wave 1's log is never touched. Pilot rows have
phase "wave2_pilot" and full-run rows phase "wave2".
"""
import argparse
import hashlib
import os
import random
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import run as wave1
from study_common import DEFAULT_RESULTS, SCENARIOS, final_rows_by, read_calls, wave2_key

MATERIALS = wave1.MATERIALS
MODELS = [
    "tinfoil/gpt-oss-120b",
    "tinfoil/deepseek-v4-1-flash",
    "greenpt/glm-5.3-flash",
    "regolo/qwen3.5-122b",
]
# Each condition's block goes before TOOLS. Full rules is wave 1's OPERATING RULES block.
CONDITION_BLOCKS = {
    "bare": None,
    "duty": "wave2/duty.txt",
    "confirm_only": "wave2/confirm_only.txt",
    "full_rules": "policy_rules.txt",
}
AMOUNTS = [50, 500, 5000, 15000]
DESTINATIONS = ["OWN", "EST", "NEW"]
PART_A_CONDITIONS = ["bare", "duty"]
PART_B_SCENARIOS = ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "S10"]
PART_C_CONDITIONS = ["bare", "full_rules"]
WORDINGS = ["W1", "W2", "W3"]
RUNS = {"A": 10, "B": 10, "C": 5}
PILOT_PART_B = {("S3", "duty"), ("S3", "confirm_only"), ("S6", "duty"), ("S6", "confirm_only")}
MAX_CONCURRENT = 4
ORDER_SEED = 20261111
LOG_NAME = "calls_wave2.jsonl"
MESSAGE_LINE = re.compile(r'^Message from Jordan: "(.*)"$', re.M)


# ---------- materials ----------

def materials_version():
    """Covers every text wave 2 sends: wave 1's materials plus materials/wave2/."""
    digest = hashlib.sha256()
    for path in sorted(MATERIALS.rglob("*.txt")):
        if path.relative_to(MATERIALS).parts[0] == "coding":
            continue  # the coding rules were not sent to the agents
        digest.update(str(path.relative_to(MATERIALS)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_system_prompt(condition):
    parts = [wave1.read_material("base_prompt.txt")]
    if CONDITION_BLOCKS[condition]:
        parts.append(wave1.read_material(CONDITION_BLOCKS[condition]))
    parts += [wave1.read_material("tools.txt"), wave1.read_material("reply_format.txt")]
    return "\n\n".join(parts)


def build_user_message(cell):
    if cell["part"] == "A":
        template = wave1.read_material(f"wave2/part_a/A-{cell['destination']}.txt")
        return template.replace("{X}", f"${cell['amount']:,}")
    text = wave1.read_material(f"scenarios/{cell['scenario']}.txt")
    if cell["wording"] == "W1":
        return text
    if len(MESSAGE_LINE.findall(text)) != 1:
        sys.exit(f"{cell['scenario']} should have exactly one 'Message from Jordan' line.")
    new = wave1.read_material(f"wave2/part_c/{cell['scenario']}_{cell['wording']}.txt")
    return MESSAGE_LINE.sub(lambda _: f'Message from Jordan: "{new}"', text)


# ---------- design ----------

def all_cells():
    cells = []
    for destination in DESTINATIONS:
        for amount in AMOUNTS:
            for condition in PART_A_CONDITIONS:
                cells.append(dict(part="A", cell_id=f"A-{destination}-{amount}", scenario=f"A-{destination}",
                                  condition=condition, wording="W1", amount=amount, destination=destination))
    for scenario in PART_B_SCENARIOS:
        for condition in CONDITION_BLOCKS:
            cells.append(dict(part="B", cell_id=f"B-{scenario}-{condition}", scenario=scenario,
                              condition=condition, wording="W1", amount=None, destination=None))
    for scenario in SCENARIOS:
        for wording in WORDINGS:
            for condition in PART_C_CONDITIONS:
                cells.append(dict(part="C", cell_id=f"C-{scenario}-{wording}-{condition}", scenario=scenario,
                                  condition=condition, wording=wording, amount=None, destination=None))
    return cells


def plan_calls(phase):
    """Every planned call as (key, cell, model, run number), in a shuffled, repeatable order."""
    if phase == "wave2_pilot":
        cells = [c for c in all_cells()
                 if c["part"] == "A" or (c["part"] == "B" and (c["scenario"], c["condition"]) in PILOT_PART_B)]
    else:
        cells = all_cells()
    planned = []
    for cell in cells:
        runs = 1 if phase == "wave2_pilot" else RUNS[cell["part"]]
        for model in MODELS:
            for run_number in range(1, runs + 1):
                key = (phase, cell["part"], cell["cell_id"], cell["condition"], model, run_number)
                planned.append((key, cell, model, run_number))
    random.Random(ORDER_SEED).shuffle(planned)
    return planned


# ---------- calls ----------

def check_models(key):
    try:
        available = wave1.fetch_model_ids(key)
    except wave1.ApiError as exc:
        print(f"Could not fetch the co-op's model list: {exc}")
        return False
    missing = [m for m in MODELS if m not in available]
    for model in MODELS:
        print(f"  {'MISSING' if model in missing else 'ok     '}  {model}")
    if missing:
        print("Nothing was sent to any model. Update MODELS in run_wave2.py once you decide on a replacement.")
    return not missing


def run_one(job, api_key, batch_id, version, log, stop):
    key, cell, model, run_number = job
    system, user = build_system_prompt(cell["condition"]), build_user_message(cell)
    attempts = []
    for number in range(1, wave1.MAX_ATTEMPTS + 1):
        if number > 1:
            time.sleep(wave1.RETRY_WAIT_SECONDS)
        outcome = wave1.attempt_call(api_key, model, system, user)
        attempts.append(outcome)
        if outcome["ok"]:
            break
        if outcome["http_status"] in (401, 402):
            stop.set()
            break
    final = attempts[-1]
    record = {
        "run_id": uuid.uuid4().hex[:12], "batch_id": batch_id, "phase": key[0],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **cell, "model": model, "provider": model.split("/", 1)[0], "run_number": run_number,
        "materials_version": version, "settings": wave1.SETTINGS,
        "system_prompt": system, "user_message": user,
        "system_prompt_sha256": wave1.sha256(system), "user_message_sha256": wave1.sha256(user),
        "status": "ok" if final["ok"] else "failed", "attempts": len(attempts),
        **{k: final[k] for k in ("response_text", "reasoning_text", "finish_reason", "input_tokens",
                                 "output_tokens", "reasoning_tokens", "latency_seconds", "error",
                                 "response_model", "response_metadata")},
        "earlier_attempts": [{k: a[k] for k in ("error", "finish_reason", "input_tokens", "output_tokens",
                                                "reasoning_tokens", "latency_seconds")}
                             for a in attempts[:-1]],
    }
    log.write(record)
    return record


def pilot_estimate(rows, remaining):
    pilot = [r for r in final_rows_by(rows, "wave2_pilot", wave2_key) if r["status"] == "ok"]
    if not pilot:
        return False
    per_model = defaultdict(int)
    for job in remaining:
        per_model[job[2]] += 1

    def mean(values):
        return sum(values) / len(values) if values else 0

    print(f"\nToken use in the wave 2 pilot ({len(pilot)} successful calls):")
    print(f"  {'model':32}{'calls':>6}{'avg in':>9}{'avg out':>9}{'of which reasoning':>20}{'avg secs':>10}{'est. tokens for remaining':>27}")
    total_in = total_out = seconds = 0
    for model in MODELS:
        mine = [r for r in pilot if r["model"] == model]
        avg_in = mean([r["input_tokens"] or 0 for r in mine])
        avg_out = mean([r["output_tokens"] or 0 for r in mine])
        avg_reason = mean([r["reasoning_tokens"] or 0 for r in mine])
        avg_secs = mean([r["latency_seconds"] or 0 for r in mine])
        count = per_model[model]
        total_in += avg_in * count
        total_out += avg_out * count
        seconds += avg_secs * count
        print(f"  {model:32}{len(mine):>6}{avg_in:>9.0f}{avg_out:>9.0f}{avg_reason:>20.0f}{avg_secs:>10.1f}"
              f"{(avg_in + avg_out) * count:>27,.0f}")
    print(f"\nScaled to the {len(remaining):,} calls to run: about {total_in:,.0f} input and {total_out:,.0f} "
          f"output tokens ({total_in + total_out:,.0f} total).")
    print(f"Estimated time: about {seconds / MAX_CONCURRENT / 60:.0f} minutes.")
    print("The pilot is mostly Part A, whose prompts are short, so Parts B and C may use somewhat more.")
    return True


def run_batch(phase, results_dir):
    path = results_dir / LOG_NAME
    rows = read_calls(path)
    version = materials_version()
    for row in rows:
        if row.get("phase") == phase and row["materials_version"] != version:
            sys.exit(f"The materials have changed since results for this phase were logged (then "
                     f"{row['materials_version']}, now {version}), so resuming would mix two versions.\n"
                     f"Nothing was sent. To start this phase again, first move the old log aside:\n"
                     f"  mv results/{LOG_NAME} results/calls_wave2_old.jsonl")

    api_key = wave1.read_key()
    print("Checking model names against the co-op's current list (free):")
    if not check_models(api_key):
        sys.exit("Stopped before spending anything.")

    planned = plan_calls(phase)
    done = {wave2_key(r) for r in rows if r.get("status") == "ok"}
    remaining = [job for job in planned if job[0] not in done]
    print(f"\n{phase}: {len(planned):,} calls planned, {len(planned) - len(remaining):,} already done, "
          f"{len(remaining):,} to run.")
    if not remaining:
        print("Nothing to do.")
        return

    if phase == "wave2":
        if not pilot_estimate(rows, remaining):
            sys.exit("\nNo successful wave 2 pilot results to base an estimate on. Run --wave2-pilot first.")
        if {r["materials_version"] for r in rows if r.get("phase") == "wave2_pilot"} - {version}:
            print("\nNote: the materials have changed since the pilot.")
        print("\nThe full run should go under caffeinate so the Mac doesn't sleep:"
              "\n  caffeinate -i python3 run_wave2.py --wave2-full")
        print(f"\nThis will make {len(remaining):,} calls and spend co-op budget.")
        try:
            answer = input("Type yes to start, anything else to cancel: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() != "yes":
            print("Cancelled. Nothing was sent.")
            return

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = wave1.Log(path)
    stop = threading.Event()
    counts = {"ok": 0, "failed": 0}
    tokens = {"input": 0, "output": 0}

    def guarded(job):
        return None if stop.is_set() else run_one(job, api_key, batch_id, version, log, stop)

    print(f"\nStarting. At most {MAX_CONCURRENT} calls at a time. Each call is saved as it finishes.\n", flush=True)
    pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
    futures = [pool.submit(guarded, job) for job in remaining]
    try:
        for finished, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            if record is None:
                continue
            counts[record["status"]] += 1
            for attempt in [record] + record["earlier_attempts"]:
                tokens["input"] += attempt["input_tokens"] or 0
                tokens["output"] += attempt["output_tokens"] or 0
            detail = (f"in={record['input_tokens']} out={record['output_tokens']}"
                      if record["status"] == "ok" else f"FAILED: {record['error'][:90]}")
            retried = " (retried)" if record["attempts"] > 1 else ""
            print(f"[{finished}/{len(remaining)}] {record['cell_id']:22} {record['condition']:12} "
                  f"{record['model']:30} run {record['run_number']:>2}  {record['latency_seconds']:.1f}s  "
                  f"{detail}{retried}", flush=True)
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        print("\nStopped. Finished calls are saved. Run the same command to pick up where it left off.")
        os._exit(130)
    pool.shutdown()

    not_started = len(remaining) - counts["ok"] - counts["failed"]
    print(f"\nDone: {counts['ok']} succeeded, {counts['failed']} failed"
          + (f", {not_started} not started" if not_started else "")
          + f". Tokens used: {tokens['input']:,} input, {tokens['output']:,} output.")
    if stop.is_set():
        print("Stopped early: the co-op refused the key or the budget is used up (HTTP 401 or 402).")
    if counts["failed"] or not_started:
        print("Running the same command again retries only the calls that didn't succeed "
              "(this spends budget for those calls).")
    print(f"Log: {path}")
    if phase == "wave2_pilot":
        print("\nRun the full wave 2 batch under caffeinate so the Mac doesn't sleep:"
              "\n  caffeinate -i python3 run_wave2.py --wave2-full")


def dry_run():
    examples = [("A-NEW-5000", "duty"), ("C-S4-W2-full_rules", "full_rules")]
    cells = {(c["cell_id"], c["condition"]): c for c in all_cells()}
    for cell_id, condition in examples:
        cell = cells[(cell_id, condition)]
        print("#" * 80)
        print(f"# {cell_id}  |  part {cell['part']}  |  condition {condition}  |  wording {cell['wording']}")
        print("#" * 80)
        print("=" * 30 + " SYSTEM PROMPT " + "=" * 30)
        print(build_system_prompt(condition))
        print("=" * 30 + " USER MESSAGE " + "=" * 31)
        print(build_user_message(cell))
        print()
    print(f"Wave 2 materials version: {materials_version()}. Nothing was sent.")


def main():
    parser = argparse.ArgumentParser(description="Batch runner for wave 2.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run-wave2", action="store_true", help="print two assembled prompts; calls nothing")
    mode.add_argument("--wave2-pilot", action="store_true", help="112 calls; spends budget")
    mode.add_argument("--wave2-full", action="store_true", help="3,440 calls, asks first; spends budget")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.dry_run_wave2:
        dry_run()
    else:
        run_batch("wave2_pilot" if args.wave2_pilot else "wave2", args.results_dir)


if __name__ == "__main__":
    main()
