#!/usr/bin/env python3
"""Copy the exact study texts out of the exported plan into materials/.

Only the sections named below are read. Everything else in the plan (notes,
decisions, the build prompt) is ignored. Stops with an error rather than guess
if a section is missing or does not hold exactly one code block.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = ["../materials/run_materials_wave1.md", "run_materials.md", "Run materials.md"]

SECTIONS = {
    "## Reply format": "reply_format.txt",
    "## Tools": "tools.txt",
    "## System prompt: bare condition": "base_prompt.txt",
    "## Policy condition: added rules": "policy_rules.txt",
}
SCENARIO_COUNT = 10


def split_sections(lines):
    """Return {heading line: body lines} for every ## and ### heading."""
    sections, current = {}, None
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"#{2,3} ", line):
            current = line.strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def only_code_block(heading, body):
    blocks, current = [], None
    for line in body:
        if line.startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
        elif current is not None:
            current.append(line)
    if len(blocks) != 1:
        sys.exit(f"Expected exactly one code block under '{heading}', found {len(blocks)}.")
    return blocks[0]


def main():
    source = next((HERE / n for n in CANDIDATES if (HERE / n).exists()), None)
    if source is None:
        sys.exit(f"Could not find the plan export. Looked for: {', '.join(CANDIDATES)}")
    sections = split_sections(source.read_text(encoding="utf-8").splitlines())

    out = HERE.parent / "materials"
    (out / "scenarios").mkdir(parents=True, exist_ok=True)

    for heading, filename in SECTIONS.items():
        if heading not in sections:
            sys.exit(f"Section '{heading}' not found in {source.name}.")
        (out / filename).write_text(only_code_block(heading, sections[heading]) + "\n", encoding="utf-8")

    for n in range(1, SCENARIO_COUNT + 1):
        matches = [h for h in sections if h.startswith(f"### S{n}:")]
        if len(matches) != 1:
            sys.exit(f"Expected one heading for S{n}, found {len(matches)}.")
        text = only_code_block(matches[0], sections[matches[0]])
        (out / "scenarios" / f"S{n}.txt").write_text(text + "\n", encoding="utf-8")

    print(f"Extracted from: {source.name}")
    for path in [out / f for f in SECTIONS.values()] + [out / "scenarios" / f"S{n}.txt" for n in range(1, SCENARIO_COUNT + 1)]:
        text = path.read_text(encoding="utf-8")
        message = re.search(r'Message from Jordan: "(.*)"', text)
        first = text.splitlines()[0]
        note = message.group(1) if message else first
        print(f"  {str(path.relative_to(HERE.parent)):28} {len(text.splitlines()):3} lines  {note[:70]}")


if __name__ == "__main__":
    main()
