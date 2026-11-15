# Agentic AI in Consumer Finance—A Study

Materials, code and data for *Agentic AI in Consumer Finance—A Study* by Max Bentovim (November 2026). The report is on [maxbentovim.com](https://maxbentovim.com) [link to be added], and a copy is in `report/`.

The study tested how open-weight AI models act when given delegated authority over a fictional consumer's accounts. Each model was told it was a personal finance agent for "Jordan Ellis", with four accounts and eleven simulated tools (transfers, bill payments, data sharing, disputes and so on, plus `ask_user` to check with Jordan). Nothing was executed and no real money was involved. Every scenario was a single turn: account data plus one request. All names of people and firms are invented.

## What was run

All calls went through the [Inference Cooperative](https://inference.coop) on 10 November 2026.

| Wave | What it tested | Models | Calls |
| --- | --- | --- | --- |
| 1 (morning) | 10 scenarios, no rules vs full rules, 3 runs per cell | gpt-oss-120b, DeepSeek V4.1 Flash, GLM-5.3 Flash, Qwen3.5-122B, Apertus-70B | 300 |
| 2, Part A (evening) | Transfers of $50 to $15,000 to the user's own account, a payee since 2024, or a payee added that day; no rules vs general duty; 10 runs | The first four | 960 |
| 2, Part B | 8 scenarios under four conditions; 10 runs | The first four | 1,280 |
| 2, Part C | All 10 scenarios with the original request and two rewordings; no rules vs full rules; 5 runs | The first four | 1,200 |

There were also 132 pilot calls. 3,739 of the 3,740 main calls returned; one Apertus call timed out.

## Folders

| Folder | Contents |
| --- | --- |
| `report/` | The report as published (Markdown and the HTML used on the website) and Figure 1 with the script that draws it |
| `materials/` | Everything the models were sent: the base prompt, rule texts, tool list, reply format, the ten scenarios, and the wave 2 additions (general duty, confirmation rule, Part A amounts and payees, Part C rewordings). `run_materials_wave1.md` and `run_materials_wave2.md` are the run plans as written before each wave. |
| `materials/coding/` | The written rules the three machine coders and I used to label how replies treated the planted memo (S3), and the instructions for the blind recode of the 67 replies where they disagreed |
| `code/` | The runners (`run.py`, `run_wave2.py`), the rule-based coders (`code.py`, `code_wave2.py`), the Metis pass (`metis_pass.py`), the machine coding of the memo (`s3_second_coding.py`, `s3_final.py`), blind sampling, the overdraw correction (`fix_overdraw.py`) and helpers |
| `code/analysis/` | `analyse.py`, which produces the numbers in the report, and its output `results.json`; `s3_table.py` rebuilds the memo table |
| `code/checks/` | Extraction and coding scripts for the full read of every S9 dispute statement and the review of Qwen's S1 grocery totals |
| `tests/` | Tests for the runner and coders. They run against a fake server on your own computer and spend nothing. |
| `data/raw/` | Every model call as logged, one JSON object per line, including retries and errors, plus the Metis and memo-coder calls |
| `data/coded/` | The coded files the report uses |
| `data/checks/` | The S9 dispute-statement read and the Qwen grocery-total review |
| `data/human_checks/` | Blind samples, their keys, hand codes and the memo relabel log |
| `data/pilot/` | Pilot runs |
| `data/superseded/` | Earlier versions of files that were later corrected, kept so every change can be traced |
| `figures/` | The LinkedIn figures and the scripts that draw them; earlier versions in `figures/superseded/` |

`DATA_DICTIONARY.md` explains every data file and column. `NOT_INCLUDED.md` lists what isn't here and why.

## Rerunning the analysis

The analysis needs only Python 3 and its standard library, and calls nothing.

```
python3 code/analysis/analyse.py
```

It reads the files in `data/` and rewrites `code/analysis/results.json`. The other files can be rebuilt the same way:

```
python3 code/analysis/s3_table.py     # data/coded/s3_final_table.csv from s3_final.csv
python3 code/checks/extract_s9.py     # data/checks/s9_statements.csv from the raw logs
python3 code/checks/code_s9.py        # data/checks/s9_full_check.csv, and prints the tallies
python3 code/checks/extract_s1.py     # data/checks/s1_all.csv from the raw logs
```

On 14 November 2026 each of these, and `analyse.py`, reproduced the published file exactly.

`code/analysis/check_report_numbers.py` runs 96 checks of the report's numbers against the data: the results tables for waves 1 and 2, the counts in the text around them, the memo table, the S9 filing counts and the exploratory observations. It prints any that differ. It doesn't cover the coding-agreement figures or the consumer-chat table. To run the tests:

```
python3 tests/test_coder.py
python3 tests/test_fixes.py
python3 tests/test_runner.py
python3 tests/test_wave2.py
```

## Rerunning the models

The runners need an Inference Cooperative API key, which they read from the macOS Keychain (service `inference-coop-api-key`); no key is stored in this repository. `python3 code/run.py --dry-run --scenario S1 --condition bare` prints one assembled prompt without calling anything. New runs and coding write to a `results/` folder at the top of the repository, not to `data/`.

Every logged call records a `materials_version`, a hash of the texts the agents were sent. The texts in `materials/` give the same hashes as the logs (`e56074b8a72a` for wave 1, `294d950857d2` for wave 2), so they are the texts that were used.

Reruns won't match exactly. Models ran at each provider's default temperature, which wasn't recorded, and the endpoints don't expose fixed model versions.

## How the data was coded

- **Rule coding.** The headline measures are counted by fixed rules from the tool calls in each reply (`code.py`, `code_wave2.py`). A blind human check of 70 replies agreed with 143 of 145 rule codes.
- **Hand coding by Claude.** 23 replies that broke the reply format were coded by hand by Claude under the same rules (`coded_by` = `hand_claude`).
- **The planted memo (S3).** Three machine coders (Metis, DeepSeek and gpt-oss) labeled every S3 reply. I coded samples blind and blind-recoded all 67 replies where the coders disagreed. `data/human_checks/s3_relabel_log.md` records every change made after the independent review.
- **Secondary measures** were scored by Metis alone and are exploratory. The Metis measure of invented facts in dispute statements was shown to be wrong and is withdrawn; `data/checks/s9_full_check.csv` replaces it with a full read of every statement by Claude, which hasn't been checked by hand.

## Use of AI

Claude (Anthropic) helped design the study, write the code, code some replies by hand as described above, and draft the report. The models under study were run through the Inference Cooperative.

## License

Code is under the MIT License (`LICENSE`). Data, materials, figures and text are under Creative Commons Attribution 4.0 (`LICENSE-DATA.md`).

## Citation

Bentovim, Max. *Agentic AI in Consumer Finance—A Study.* November 2026. https://maxbentovim.com [link to be added]
