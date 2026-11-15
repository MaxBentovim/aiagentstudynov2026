#!/usr/bin/env python3
"""Copy the wave 2 texts out of the exported plan into materials/wave2/.

Reads only the "## Materials" section of run_materials_v2.md. In its code blocks the
first line is a label for the doc and is not copied. The base prompt, tools, reply
format, full rules and S1-S10 are not redefined there, so wave 2 reuses wave 1's
files in materials/ unchanged.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = [HERE.parent / "materials" / "run_materials_wave2.md", HERE / "run_materials_v2.md"]
OUT = HERE.parent / "materials" / "wave2"
BLOCKS = {
    "DUTY": "duty.txt",
    "CONFIRM-ONLY": "confirm_only.txt",
    "A-OWN": "part_a/A-OWN.txt",
    "A-EST": "part_a/A-EST.txt",
    "A-NEW": "part_a/A-NEW.txt",
}
REWORDING_ROW = re.compile(r'^\| (S\d+) \| "(.+)" \| "(.+)" \|$')


def materials_section(lines):
    """Lines from '## Materials' up to the next '## ' heading outside a code block."""
    inside, in_code, out = False, False, []
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("## "):
            if inside:
                break
            inside = line.strip() == "## Materials"
            continue
        if inside:
            out.append(line)
    if not out:
        sys.exit("No '## Materials' section found.")
    return out


def code_blocks(lines):
    blocks, current = [], None
    for line in lines:
        if line.startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
        elif current is not None:
            current.append(line)
    return blocks


def main():
    source = next((p for p in CANDIDATES if p.exists()), None)
    if source is None:
        sys.exit("Could not find run_materials_v2.md in this folder or in results/.")
    section = materials_section(source.read_text(encoding="utf-8").splitlines())

    found = {}
    for block in code_blocks(section):
        label = block[0].split()[0]
        if label not in BLOCKS:
            sys.exit(f"Unexpected code block labelled '{block[0]}'.")
        if label in found:
            sys.exit(f"Two code blocks labelled {label}.")
        found[label] = "\n".join(block[1:])
    missing = set(BLOCKS) - set(found)
    if missing:
        sys.exit(f"Missing code blocks: {', '.join(sorted(missing))}")
    for label in ("A-OWN", "A-EST", "A-NEW"):
        if found[label].count("{X}") != 1:
            sys.exit(f"{label} should contain {{X}} exactly once.")

    rewordings = {}
    for line in section:
        if match := REWORDING_ROW.match(line.strip()):
            rewordings[match.group(1)] = (match.group(2), match.group(3))
    expected = [f"S{n}" for n in range(1, 11)]
    if sorted(rewordings, key=lambda s: int(s[1:])) != expected:
        sys.exit(f"Expected rewordings for S1-S10, found: {', '.join(rewordings)}")

    (OUT / "part_a").mkdir(parents=True, exist_ok=True)
    (OUT / "part_c").mkdir(parents=True, exist_ok=True)
    for label, filename in BLOCKS.items():
        (OUT / filename).write_text(found[label] + "\n", encoding="utf-8")
    for scenario, (w2, w3) in rewordings.items():
        (OUT / "part_c" / f"{scenario}_W2.txt").write_text(w2 + "\n", encoding="utf-8")
        (OUT / "part_c" / f"{scenario}_W3.txt").write_text(w3 + "\n", encoding="utf-8")

    print(f"Extracted from: {source.relative_to(HERE.parent)}")
    for label, filename in BLOCKS.items():
        text = found[label]
        print(f"  materials/wave2/{filename:22} {len(text.splitlines())} lines (label '{label}' dropped)")
        for line in text.splitlines():
            print(f"      | {line}")
    print("  materials/wave2/part_c/  20 files, W2 and W3 for each scenario:")
    for scenario in expected:
        w2, w3 = rewordings[scenario]
        print(f"      {scenario:4} W2: {w2}")
        print(f"           W3: {w3}")


if __name__ == "__main__":
    main()
