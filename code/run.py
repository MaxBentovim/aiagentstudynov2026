#!/usr/bin/env python3
"""Batch runner for the personal finance agent study. See README.md.

  --dry-run --scenario S3 --condition policy   print one assembled prompt (free)
  --check-models                               compare model names with the co-op's list (free)
  --pilot                                      20 calls (spends budget)
  --full                                       300 calls, asks first (spends budget)

The API key is read from the macOS Keychain each run and held only in memory.
Nothing here executes a tool call: the models' replies are only recorded.
"""
import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from study_common import DEFAULT_RESULTS, HERE, ROOT, SCENARIOS, cell_key, final_rows, read_calls

# Same endpoint and Keychain entry as the inference-coop server in ~/Developer/coop-mcp.
BASE_URL = os.environ.get("COOP_BASE_URL", "https://gateway.inference.coop/v1").rstrip("/")
KEYCHAIN_SERVICE = "inference-coop-api-key"
KEYCHAIN_ACCOUNT = "coop-mcp"
IS_LOCAL_TEST = BASE_URL.startswith("http://127.0.0.1")

MODELS = [
    "tinfoil/gpt-oss-120b",
    "tinfoil/deepseek-v4-1-flash",
    "greenpt/glm-5.3-flash",
    "regolo/qwen3.5-122b",
    "regolo/apertus-70b",
]
CONDITIONS = ["bare", "policy"]
PILOT_SCENARIOS = ["S3", "S6"]
FULL_RUNS = 3
MAX_CONCURRENT = 3
MAX_ATTEMPTS = 2  # first try plus one retry
REQUEST_TIMEOUT_SECONDS = 200  # just past the gateway's ~180 s cutoff, so its own error reaches us
RETRY_WAIT_SECONDS = 0 if IS_LOCAL_TEST else 5
ORDER_SEED = 20261110  # calls run in a shuffled, repeatable order

SETTINGS = {
    "temperature": "model default (not sent in the request)",
    "max_tokens": "not sent in the request",
    "fields_sent": ["model", "messages"],
    "stream": False,
}

MATERIALS = ROOT / "materials"
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


# ---------- materials ----------

def read_material(name):
    return (MATERIALS / name).read_text(encoding="utf-8").rstrip("\n")


def materials_version():
    digest = hashlib.sha256()
    for path in sorted(MATERIALS.rglob("*.txt")):
        if path.relative_to(MATERIALS).parts[0] in ("wave2", "coding"):
            continue  # wave 2's texts and the coding rules must not change wave 1's materials version
        digest.update(str(path.relative_to(MATERIALS)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_system_prompt(condition):
    parts = [read_material("base_prompt.txt")]
    if condition == "policy":
        parts.append(read_material("policy_rules.txt"))
    parts += [read_material("tools.txt"), read_material("reply_format.txt")]
    return "\n\n".join(parts)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- talking to the co-op ----------

class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def read_key():
    if IS_LOCAL_TEST:  # the automated tests use a fake server and must never see the real key
        return "test-key"
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        sys.exit("Could not read the macOS Keychain.")
    key = result.stdout.strip()
    if result.returncode != 0 or not key:
        sys.exit("No co-op API key found in the Keychain. It is the same entry your "
                 "inference-coop tools use; see ~/Developer/coop-mcp/README.md.")
    return key


def scrub(text):
    return KEY_PATTERN.sub("sk-***", str(text))[:500]


def http_json(method, path, key, body=None, timeout=REQUEST_TIMEOUT_SECONDS):
    request = urllib.request.Request(
        BASE_URL + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "agent-study-runner/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"HTTP {exc.code}: {scrub(exc.read().decode('utf-8', 'replace'))}", exc.code) from None
    except TimeoutError:
        raise ApiError(f"timed out after {timeout} s") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"connection problem: {scrub(exc.reason)}") from None
    except OSError as exc:
        raise ApiError(f"connection problem: {scrub(exc)}") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(f"server sent something that isn't JSON: {scrub(raw[:200])}") from None


def fetch_model_ids(key):
    return sorted(m["id"] for m in http_json("GET", "/models", key, timeout=30)["data"])


def check_models(key):
    """Print the comparison and return True only if every study model is offered."""
    try:
        available = fetch_model_ids(key)
    except ApiError as exc:
        print(f"Could not fetch the co-op's model list: {exc}")
        return False
    missing = [m for m in MODELS if m not in available]
    for model in MODELS:
        print(f"  {'ok     ' if model not in missing else 'MISSING'}  {model}")
    if missing:
        print("\nThese names are not on the co-op's current list:")
        for model in missing:
            stem = model.split("/", 1)[1].split("-")[0]
            similar = [a for a in available if stem in a]
            print(f"  {model}  (similar: {', '.join(similar) or 'none'})")
        print("Nothing was sent to any model. Update MODELS in run.py once you decide on a replacement.")
    return not missing


def attempt_call(key, model, system, user):
    """One request. Returns a dict of what happened and never raises for API trouble."""
    body = {"model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    started = time.monotonic()
    outcome = {"ok": False, "response_text": None, "reasoning_text": None, "finish_reason": None,
               "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
               "response_model": None, "response_metadata": None, "error": None, "http_status": None}
    try:
        data = http_json("POST", "/chat/completions", key, body)
    except ApiError as exc:
        outcome.update(error=str(exc), http_status=exc.status)
        outcome["latency_seconds"] = round(time.monotonic() - started, 2)
        return outcome
    outcome["latency_seconds"] = round(time.monotonic() - started, 2)

    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    choices = data.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    outcome.update(
        response_text=message.get("content"),
        reasoning_text=message.get("reasoning_content") or message.get("reasoning"),
        finish_reason=choices[0].get("finish_reason") if choices else None,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        reasoning_tokens=details.get("reasoning_tokens"),
        response_model=data.get("model"),
        response_metadata={k: v for k, v in data.items() if k not in ("choices", "usage")},
    )
    if data.get("error"):
        outcome["error"] = scrub(json.dumps(data["error"]))
    elif not (outcome["response_text"] or "").strip():
        outcome["error"] = f"empty reply (finish reason: {outcome['finish_reason']})"
    else:
        outcome["ok"] = True
    return outcome


# ---------- batches ----------

def plan_calls(phase):
    scenarios = PILOT_SCENARIOS if phase == "pilot" else SCENARIOS
    runs = 1 if phase == "pilot" else FULL_RUNS
    planned = [(phase, s, c, m, r)
               for s in scenarios for c in CONDITIONS for m in MODELS for r in range(1, runs + 1)]
    random.Random(ORDER_SEED).shuffle(planned)
    return planned


class Log:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        # If a crash left a half-written last line, start the next entry on a fresh line.
        if path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n")

    def write(self, record):
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def run_one(cell, key, batch_id, version, log, stop):
    phase, scenario, condition, model, run_number = cell
    system = build_system_prompt(condition)
    user = read_material(f"scenarios/{scenario}.txt")
    attempts = []
    for number in range(1, MAX_ATTEMPTS + 1):
        if number > 1:
            time.sleep(RETRY_WAIT_SECONDS)
        outcome = attempt_call(key, model, system, user)
        attempts.append(outcome)
        if outcome["ok"]:
            break
        if outcome["http_status"] in (401, 402):
            stop.set()  # bad key or budget used up: more calls cannot succeed
            break
    final = attempts[-1]
    record = {
        "run_id": uuid.uuid4().hex[:12], "batch_id": batch_id, "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario": scenario, "condition": condition, "model": model,
        "provider": model.split("/", 1)[0], "run_number": run_number,
        "materials_version": version, "settings": SETTINGS,
        "system_prompt": system, "user_message": user,
        "system_prompt_sha256": sha256(system), "user_message_sha256": sha256(user),
        "status": "ok" if final["ok"] else "failed", "attempts": len(attempts),
        **{k: final[k] for k in ("response_text", "reasoning_text", "finish_reason", "input_tokens",
                                 "output_tokens", "reasoning_tokens", "latency_seconds", "error",
                                 "response_model", "response_metadata")},
        # Earlier tries may also have used tokens, so keep them for the cost count.
        "earlier_attempts": [{k: a[k] for k in ("error", "finish_reason", "input_tokens", "output_tokens",
                                                "reasoning_tokens", "latency_seconds")}
                             for a in attempts[:-1]],
    }
    log.write(record)
    return record


def stop_if_materials_changed(rows, version):
    for row in rows:
        if row["materials_version"] != version:
            sys.exit(f"The materials have changed since results for this phase were logged "
                     f"(then {row['materials_version']}, now {version}), so resuming would mix two "
                     "versions of the study.\nNothing was sent. To start this phase again, first "
                     "move the old log aside:\n  mv results/calls.jsonl results/calls_old.jsonl")


def pilot_estimate(rows, planned_remaining):
    """Print the pilot's token use and scale it up. Returns False if there is no pilot to show."""
    pilot = final_rows(rows, "pilot")
    usable = [r for r in pilot if r["status"] == "ok"]
    if not usable:
        return False
    remaining_by_model = defaultdict(int)
    for cell in planned_remaining:
        remaining_by_model[cell[3]] += 1

    print(f"\nToken use in the pilot ({len(usable)} of {len(pilot)} calls succeeded; S3 and S6 only):")
    print(f"  {'model':32}{'calls':>6}{'avg in':>9}{'avg out':>9}{'of which reasoning':>20}{'avg secs':>10}{'est. total for remaining':>26}")
    total_in = total_out = 0
    seconds = 0.0
    def mean(values):
        return sum(values) / len(values) if values else 0
    for model in MODELS:
        mine = [r for r in usable if r["model"] == model]
        avg_in = mean([r["input_tokens"] or 0 for r in mine])
        avg_out = mean([r["output_tokens"] or 0 for r in mine])
        avg_reason = mean([r["reasoning_tokens"] or 0 for r in mine])
        avg_secs = mean([r["latency_seconds"] or 0 for r in mine])
        count = remaining_by_model[model]
        total_in += avg_in * count
        total_out += avg_out * count
        seconds += avg_secs * count
        print(f"  {model:32}{len(mine):>6}{avg_in:>9.0f}{avg_out:>9.0f}{avg_reason:>20.0f}{avg_secs:>10.1f}"
              f"{avg_in * count + avg_out * count:>26,.0f}")
    print(f"\nEstimated for the remaining calls: about {total_in:,.0f} input and {total_out:,.0f} output tokens "
          f"({total_in + total_out:,.0f} total).")
    print(f"Estimated time: about {seconds / MAX_CONCURRENT / 60:.0f} minutes.")
    print("This scales up S3 and S6, which are short scenarios; other scenarios may use somewhat "
          "more or less. A retry would add to it.")
    return True


def run_batch(phase, results_dir):
    path = results_dir / "calls.jsonl"
    rows = read_calls(path)
    version = materials_version()
    stop_if_materials_changed([r for r in rows if r.get("phase") == phase], version)

    key = read_key()
    print("Checking model names against the co-op's current list (free):")
    if not check_models(key):
        sys.exit("Stopped before spending anything.")

    planned = plan_calls(phase)
    done = {cell_key(r) for r in rows if r.get("status") == "ok"}
    remaining = [cell for cell in planned if cell not in done]
    previously_failed = {cell_key(r) for r in rows if r.get("phase") == phase} - done
    print(f"\n{phase}: {len(planned)} calls planned, {len(planned) - len(remaining)} already done, "
          f"{len(remaining)} to run"
          + (f" (including {len(previously_failed & set(remaining))} that failed earlier)." if previously_failed else "."))
    if not remaining:
        print("Nothing to do.")
        return

    if phase == "full":
        if not pilot_estimate(rows, remaining):
            sys.exit("\nNo successful pilot results to base a cost estimate on. Run --pilot first.")
        pilot_versions = {r["materials_version"] for r in rows if r.get("phase") == "pilot"}
        if pilot_versions - {version}:
            print("\nNote: the materials have changed since the pilot.")
        print("\nThe full batch should run under caffeinate so the Mac doesn't sleep:"
              "\n  caffeinate -i python3 run.py --full")
        print(f"\nThis will make {len(remaining)} calls and spend co-op budget.")
        try:
            answer = input("Type yes to start, anything else to cancel: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() != "yes":
            print("Cancelled. Nothing was sent.")
            return

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = Log(path)
    stop = threading.Event()
    counts = {"ok": 0, "failed": 0}
    tokens = {"input": 0, "output": 0}

    def guarded(cell):
        return None if stop.is_set() else run_one(cell, key, batch_id, version, log, stop)

    print(f"\nStarting. At most {MAX_CONCURRENT} calls at a time. Each call is saved as it finishes.\n", flush=True)
    pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
    futures = [pool.submit(guarded, cell) for cell in remaining]
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
            print(f"[{finished}/{len(remaining)}] {record['scenario']:3} {record['condition']:6} "
                  f"{record['model']:30} run {record['run_number']}  {record['latency_seconds']:.1f}s  {detail}{retried}",
                  flush=True)
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
    if phase == "pilot":
        print("\nBefore the full batch, remember to run it under caffeinate so the Mac doesn't sleep:"
              "\n  caffeinate -i python3 run.py --full")


def dry_run(scenario, condition):
    print("=" * 30 + f" SYSTEM PROMPT ({condition}) " + "=" * 30)
    print(build_system_prompt(condition))
    print("=" * 30 + f" USER MESSAGE ({scenario}) " + "=" * 30)
    print(read_material(f"scenarios/{scenario}.txt"))
    print("=" * 80)
    print(f"Materials version: {materials_version()}. Nothing was sent.")


def main():
    parser = argparse.ArgumentParser(description="Batch runner for the agent study.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print one assembled prompt; calls nothing")
    mode.add_argument("--check-models", action="store_true", help="compare model names with the co-op's list; free")
    mode.add_argument("--pilot", action="store_true", help="20 calls; spends budget")
    mode.add_argument("--full", action="store_true", help="300 calls, asks first; spends budget")
    parser.add_argument("--scenario", choices=SCENARIOS, help="for --dry-run")
    parser.add_argument("--condition", choices=CONDITIONS, help="for --dry-run")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.dry_run:
        if not args.scenario or not args.condition:
            parser.error("--dry-run needs --scenario and --condition, e.g. --scenario S3 --condition policy")
        dry_run(args.scenario, args.condition)
    elif args.check_models:
        print("Comparing study models with the co-op's current list:")
        sys.exit(0 if check_models(read_key()) else 1)
    else:
        run_batch("pilot" if args.pilot else "full", args.results_dir)


if __name__ == "__main__":
    main()
