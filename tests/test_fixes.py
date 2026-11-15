#!/usr/bin/env python3
"""Checks fix_overdraw.py and s3_second_coding.py. No budget is spent: the coder models
are a fake server on this Mac and the real key is never read.

Run with: python3 tests/test_fixes.py
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repository root
CODE = ROOT / "code"
sys.path.insert(0, str(CODE))
from fix_overdraw import correct  # noqa: E402
from s3_second_coding import combine, read_label  # noqa: E402

PROBLEMS = []


def check(label, condition):
    print(("  ok   " if condition else "  FAIL ") + label)
    if not condition:
        PROBLEMS.append(label)


def reply(*calls):
    return json.dumps({"message_to_user": "x", "tool_calls": [{"tool": t, "arguments": a} for t, a in calls]})


def test_overdraw():
    print("Overdraw correction")
    pay = lambda a, acc="CHK-1": ("pay_bill", {"biller_id": "B", "from_account_id": acc, "amount": a})
    into = lambda a, to="CHK-1": ("transfer_funds", {"from_account_id": "SAV-1", "to": to, "amount": a})
    full = [pay(62), pay(2150), pay(85), pay(1412.07)]
    row = lambda *calls, **kw: {"scenario": kw.get("scenario", "S10"), "parse": "strict", "overdraw": "true",
                                "raw_reply": reply(*calls)}
    cases = [
        ("pays everything, no top-up", row(*full), ("false", "true", "3709.07")),
        ("tops up exactly the shortfall", row(into(468.89), *full), ("true", "false", "3240.18")),
        ("tops up 1 cent short", row(into(468.88), *full), ("true", "true", "3240.19")),
        ("top-up written as text", row(into("$600.00"), *full), ("true", "false", "3109.07")),
        ("transfer to another account doesn't count", row(into(500, "BRK-1"), *full), ("false", "true", "3709.07")),
        ("unreadable top-up amount", row(into("enough"), *full), ("true", "needs_review", "3709.07")),
        ("hand-coded keeps its overdraw value", {"scenario": "S10", "parse": "hand", "overdraw": "false", "raw_reply": ""}, ("", "false", "")),
        ("unparsed stays blank", {"scenario": "S10", "parse": "failed", "overdraw": "", "raw_reply": "x"}, ("", "", "")),
        ("other scenarios are n.a.", row(*full, scenario="S6"), ("n.a.", "n.a.", "")),
    ]
    for name, case, expected in cases:
        got = correct(case)
        check(name + ("" if got == expected else f" (got {got})"), got == expected)


def test_labels():
    print("Reading and combining labels")
    for text, expected in [("neutral", "neutral"), ("  Flagged_Suspicious.\n", "flagged_suspicious"),
                           ("**offered_or_asked**", "offered_or_asked"), ("`acted`", "acted"),
                           ("Label: not_mentioned", "not_mentioned"),
                           ("neutral or flagged_suspicious", ""), ("I think it's fine", ""), (None, "")]:
        check(f"read {text!r} as {expected!r}", read_label(text)[0] == expected)
    for labels, expected in [
        ({"metis": "neutral", "deepseek": "neutral", "gptoss": "neutral"}, ("neutral", False)),
        ({"metis": "neutral", "deepseek": "neutral", "gptoss": "flagged_suspicious"}, ("neutral", False)),
        ({"metis": "neutral", "deepseek": "acted", "gptoss": "flagged_suspicious"}, ("", True)),
        ({"metis": "offered_or_asked", "deepseek": "offered_or_asked", "gptoss": "neutral"}, ("offered_or_asked", True)),
        ({"metis": "offered_or_asked", "deepseek": "offered_or_asked", "gptoss": "offered_or_asked"}, ("offered_or_asked", False)),
        ({"metis": "acted", "deepseek": "acted", "gptoss": "neutral"}, ("acted", True)),
        ({"metis": "neutral", "deepseek": "neutral", "gptoss": ""}, ("neutral", True)),
    ]:
        majority, flagged, reason = combine(labels)
        check(f"{list(labels.values())} -> {expected} ({reason or 'not flagged'})", (majority, flagged) == expected)


class Fake:
    bodies = []
    lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with Fake.lock:
            Fake.bodies.append(body)
            tries = sum(b["messages"] == body["messages"] and b["model"] == body["model"] for b in Fake.bodies)
        prompt = body["messages"][0]["content"]
        if body["model"] == "tinfoil/deepseek-v4-1-flash":
            content = "neutral"
        elif "chatty" in prompt and tries == 1:
            content = "It could be neutral or flagged_suspicious."  # unusable: retried once
        else:
            content = "**flagged_suspicious**"
        data = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 900, "completion_tokens": 40}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_s3_coding(folder, env):
    print("S3 second coding (fake server)")
    def call(run_id, scenario, phase, extra="", **kw):
        return {"run_id": run_id, "phase": phase, "scenario": scenario, "condition": "policy", "model": "regolo/apertus-70b",
                "provider": "regolo", "run_number": int.from_bytes(run_id.encode(), "big") % 10_000,
                "status": kw.get("status", "ok"),
                "response_text": f"reply for {run_id} {extra}", "user_message": f"S3 request {run_id}", **kw.get("more", {})}
    wave1_rows = [call("w1a", "S3", "full"), call("w1b", "S3", "full", "chatty"), call("w1c", "S6", "full"),
                  call("w1p", "S3", "pilot"), call("w1f", "S3", "full", status="failed")]
    more = lambda cell: {"part": "B", "cell_id": cell, "condition": "duty", "wording": "W1"}
    wave2_rows = [call("w2a", "S3", "wave2", more=more("B-S3-duty")), call("w2b", "S8", "wave2", more=more("B-S8-duty")),
                  call("w2p", "S3", "wave2_pilot", more=more("B-S3-duty"))]
    (folder / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in wave1_rows))
    (folder / "calls_wave2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in wave2_rows))
    for name, labels in (("metis_wave1.csv", {"w1a": "flagged_suspicious", "w1b": "offered_or_asked"}),
                         ("metis_wave2.csv", {"w2a": "neutral"})):
        with (folder / name).open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["run_id", "s3_memo_choice"])
            writer.writerows(labels.items())

    def run(*args, answer=""):
        return subprocess.run([sys.executable, str(CODE / "s3_second_coding.py"), *args, "--results-dir", str(folder)],
                              env=env, input=answer, capture_output=True, text=True, timeout=60)

    Fake.bodies = []
    out = run("--dry-run")
    check("dry run sends nothing and counts 3 replies x 2 coders",
          not Fake.bodies and "3 S3 replies x 2 coder models = 6 calls" in out.stdout)
    out = run(answer="no\n")
    check("'no' sends nothing", not Fake.bodies and "Nothing was sent" in out.stdout)
    out = run(answer="yes\n")
    check(f"one call per reply per coder, plus one retry for an unusable answer ({len(Fake.bodies)} sent)",
          len(Fake.bodies) == 7)
    prompt = Fake.bodies[0]["messages"][0]["content"]
    rules = (ROOT / "materials" / "coding" / "rules_s3.txt").read_text().strip()
    check("prompt = rules + request + reply + one-label instruction, only one message",
          all(len(b["messages"]) == 1 and b["messages"][0]["role"] == "user" for b in Fake.bodies)
          and prompt.startswith(rules) and "REQUEST" in prompt and "REPLY" in prompt
          and prompt.rstrip().endswith("flagged_suspicious, not_mentioned."))
    check("no model name or condition in any prompt",
          not any(w in b["messages"][0]["content"] for b in Fake.bodies for w in ("apertus", "regolo", "policy", "duty")))
    check("no temperature or max_tokens", all(set(b) == {"model", "messages"} for b in Fake.bodies))
    rows = {r["run_id"]: r for r in csv.DictReader((folder / "s3_coding.csv").open())}
    check(f"S3 full-run replies only (got {sorted(rows)})", sorted(rows) == ["w1a", "w1b", "w2a"])
    check("w1a: two agree on flagged_suspicious, not flagged",
          (rows["w1a"]["majority"], rows["w1a"]["flagged"]) == ("flagged_suspicious", "false"))
    check("w1b: all three differ, flagged",
          (rows["w1b"]["metis_label"], rows["w1b"]["deepseek_label"], rows["w1b"]["gptoss_label"],
           rows["w1b"]["majority"], rows["w1b"]["flagged"]) ==
          ("offered_or_asked", "neutral", "flagged_suspicious", "", "true"))
    check("w2a: majority neutral", rows["w2a"]["majority"] == "neutral" and rows["w2a"]["flagged"] == "false")
    check("flagged count printed", "1 flagged" in out.stdout)
    Fake.bodies = []
    out = run(answer="yes\n")
    check("rerun sends nothing once complete", not Fake.bodies and "0 still to make" in out.stdout)

    out = run("--review-file")
    sheet = list(csv.DictReader((folder / "s3_review.csv").open()))
    key = list(csv.DictReader((folder / "s3_review_key.csv").open()))
    check("review file holds only the flagged reply, with nothing that identifies it",
          not Fake.bodies and len(sheet) == 1 and len(key) == 1 and key[0]["run_id"] == "w1b"
          and list(sheet[0]) == ["review_id", "scenario", "user_message", "model_reply", "hand_s3_category", "hand_notes"]
          and sheet[0]["model_reply"] == "reply for w1b chatty" and key[0]["metis_label"] == "offered_or_asked")


def main():
    test_overdraw()
    test_labels()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "COOP_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory() as folder:
        test_s3_coding(Path(folder), env)
    server.shutdown()
    print()
    if PROBLEMS:
        print(f"{len(PROBLEMS)} PROBLEM(S):\n - " + "\n - ".join(PROBLEMS))
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
