#!/usr/bin/env python3
"""Exercises run.py against a fake co-op server on this Mac.

No request leaves the computer, the real key is never read, and no budget is spent.
Results go to a temporary folder, not results/.

Run with: python3 tests/test_runner.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repository root
CODE = ROOT / "code"
MODELS = ["tinfoil/gpt-oss-120b", "tinfoil/deepseek-v4-1-flash", "greenpt/glm-5.3-flash",
          "regolo/qwen3.5-122b", "regolo/apertus-70b"]


class Fake:
    lock = threading.Lock()
    active = peak = 0
    bodies = []
    catalog = list(MODELS)
    behaviour = staticmethod(lambda model, count: "ok")
    per_model_counts = Counter()

    @classmethod
    def reset(cls, behaviour=lambda model, count: "ok"):
        cls.bodies, cls.per_model_counts, cls.peak = [], Counter(), 0
        cls.behaviour = staticmethod(behaviour)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(200, {"data": [{"id": m} for m in Fake.catalog]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with Fake.lock:
            Fake.active += 1
            Fake.peak = max(Fake.peak, Fake.active)
            Fake.bodies.append(body)
            Fake.per_model_counts[body["model"]] += 1
            count = Fake.per_model_counts[body["model"]]
        time.sleep(0.02)
        action = Fake.behaviour(body["model"], count)
        with Fake.lock:
            Fake.active -= 1
        if action in (500, 402):
            return self.send(action, {"error": "boom"})
        content = "" if action == "empty" else '{"message_to_user":"hi","tool_calls":[]}'
        self.send(200, {"model": body["model"],
                        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1000, "completion_tokens": 200,
                                  "completion_tokens_details": {"reasoning_tokens": 50}}})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "COOP_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}
    problems = []

    def check(label, condition):
        print(("  ok   " if condition else "  FAIL ") + label)
        if not condition:
            problems.append(label)

    with tempfile.TemporaryDirectory() as folder:
        results = Path(folder)
        log = results / "calls.jsonl"

        def run(mode, answer=""):
            return subprocess.run([sys.executable, str(CODE / "run.py"), mode, "--results-dir", str(results)],
                                  env=env, input=answer, capture_output=True, text=True, timeout=120)

        def rows():
            # Leave out the half-written line this test adds on purpose.
            return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()
                    if l.endswith("}")] if log.exists() else []

        print("Model name check")
        Fake.catalog = [m for m in MODELS if m != "regolo/apertus-70b"]
        Fake.reset()
        out = run("--pilot")
        check("a missing model stops the batch before any call", out.returncode != 0 and not Fake.bodies)
        check("the missing name is reported", "regolo/apertus-70b" in out.stdout)
        Fake.catalog = list(MODELS)

        print("Full batch needs a pilot first")
        Fake.reset()
        out = run("--full", "yes\n")
        check("refuses with no pilot to estimate from", out.returncode != 0 and not Fake.bodies)

        print("Pilot with one retry that recovers, one empty reply that recovers, one permanent failure")
        def flaky(model, count):
            if model == "tinfoil/gpt-oss-120b" and count == 1:
                return 500
            if model == "regolo/qwen3.5-122b" and count == 2:
                return "empty"
            if model == "regolo/apertus-70b":
                return 500 if count <= 2 else "ok"
            return "ok"
        Fake.reset(flaky)
        out = run("--pilot")
        data = rows()
        check(f"writes 20 lines (got {len(data)})", len(data) == 20)
        check(f"never more than 3 at once (peak {Fake.peak})", Fake.peak <= 3)
        check("no temperature or max_tokens sent", all(set(b) == {"model", "messages"} for b in Fake.bodies))
        check(f"retries add up (got {len(Fake.bodies)} requests, expected 23)", len(Fake.bodies) == 23)
        failed = [r for r in data if r["status"] == "failed"]
        check("one call fails after its retry and is logged", len(failed) == 1 and failed[0]["attempts"] == 2 and failed[0]["error"])
        check("tokens from a retried empty reply are kept", any(r["earlier_attempts"] and r["earlier_attempts"][0]["input_tokens"] == 1000 for r in data))
        ok = next(r for r in data if r["status"] == "ok" and not r["earlier_attempts"])
        expected_fields = {"run_id", "timestamp", "scenario", "condition", "model", "provider", "run_number", "system_prompt",
                           "user_message", "response_text", "finish_reason", "input_tokens", "output_tokens",
                           "reasoning_tokens", "latency_seconds", "error", "settings", "materials_version"}
        check("every requested field is logged", expected_fields <= set(ok))
        check("token counts recorded", (ok["input_tokens"], ok["output_tokens"], ok["reasoning_tokens"]) == (1000, 200, 50))
        check("pilot covers S3 and S6 only", {r["scenario"] for r in data} == {"S3", "S6"})
        policy = next(r for r in data if r["condition"] == "policy")["system_prompt"]
        bare = next(r for r in data if r["condition"] == "bare")["system_prompt"]
        check("policy prompt has rules, bare doesn't", "OPERATING RULES" in policy and "OPERATING RULES" not in bare)
        check("policy order is base, rules, tools, format",
              policy.index("JORDAN'S ACCOUNTS") < policy.index("OPERATING RULES") < policy.index("TOOLS\n") < policy.index("RESPONSE FORMAT\nReply"))
        check("the only difference is the rules block",
              policy.replace((ROOT / "materials/policy_rules.txt").read_text(encoding="utf-8").rstrip("\n") + "\n\n", "") == bare)

        print("Resume after a half-written line")
        with log.open("a", encoding="utf-8") as handle:
            handle.write('{"run_id": "cut off')
        Fake.reset()
        run("--pilot")
        check(f"reruns only the failed call (sent {len(Fake.bodies)})", len(Fake.bodies) == 1)
        Fake.reset()
        out = run("--pilot")
        check("nothing left to do on a third run", not Fake.bodies and "Nothing to do" in out.stdout)

        print("Full batch gate")
        Fake.reset()
        out = run("--full", "no\n")
        check("answering no sends nothing", not Fake.bodies and "Nothing was sent" in out.stdout)
        check("shows call count and pilot tokens", "300 calls" in out.stdout and "1000" in out.stdout)
        check("reminds about caffeinate", "caffeinate" in out.stdout)
        Fake.reset()
        out = run("--full", "")
        check("no answer at all sends nothing", not Fake.bodies)

        print("Full batch stops when the budget runs out")
        Fake.reset(lambda model, count: 402)
        out = run("--full", "yes\n")
        check(f"stops early (sent {len(Fake.bodies)} requests)", 0 < len(Fake.bodies) < 12 and "Stopped early" in out.stdout)

        print("Full batch resumes and completes")
        Fake.reset()
        out = run("--full", "yes\n")
        full = [r for r in rows() if r["phase"] == "full" and r["status"] == "ok"]
        check(f"300 successful full calls, pilot not counted in them (got {len(full)})", len(full) == 300)
        cells = Counter((r["scenario"], r["condition"], r["model"]) for r in full)
        check("each scenario x condition x model has 3 runs", len(cells) == 100 and set(cells.values()) == {3})
        Fake.reset()
        out = run("--full", "yes\n")
        check("rerun sends nothing once complete", not Fake.bodies and "Nothing to do" in out.stdout)

        print("Materials edited after results exist")
        scratch_version = ROOT / "materials" / "policy_rules.txt"
        original = scratch_version.read_bytes()
        try:
            scratch_version.write_bytes(original + b"extra line\n")
            Fake.reset()
            out = run("--full", "yes\n")
            check("refuses to mix versions", out.returncode != 0 and not Fake.bodies and "changed" in out.stderr)
        finally:
            scratch_version.write_bytes(original)

    server.shutdown()
    print()
    if problems:
        print(f"{len(problems)} PROBLEM(S): " + "; ".join(problems))
        sys.exit(1)
    print("All runner checks passed.")


if __name__ == "__main__":
    main()
