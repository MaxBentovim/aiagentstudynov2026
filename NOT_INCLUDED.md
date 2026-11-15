# What isn't included

The report says this repository holds the runner, coding and analysis scripts, the coder prompts, the consumer-chat transcripts and a data dictionary, and lists here anything that couldn't be included.

## Not recorded, so not available

- **Model settings.** Models ran at each provider's default temperature and other sampling settings; no settings were sent and the defaults weren't recorded. The logs show this in each call's `settings` field.
- **Fixed model versions.** The co-op endpoints don't expose pinned model versions, so the exact weights behind each reply can't be named. The `system_fingerprint` and `response_model` fields record what each provider returned.
- **Three original blind memo codes.** After comparing my 20 blind wave 2 S3 codes with the machine coders, I revised 3 of them. The originals weren't kept separately, so the pre-review agreement figures in the report can't be rebuilt from these files. The codes in the files are the revised ones.

## Removed or held back

- **The API key.** The runners read an Inference Cooperative key from the macOS Keychain at run time. No key appears in any file. To rerun the models you need your own co-op key.
- **Co-op gateway configuration.** Two timeout errors in wave 1 quoted the gateway's internal fallback settings. That text was replaced with `[Gateway configuration details removed for publication.]` in `data/raw/calls.jsonl` and in the `error` column of `coded_full_v2.csv`, `coded_full_metis.csv` and `data/superseded/coded_full.csv`. Nothing else in the logs was changed.
- **Font files.** The figure scripts embed Source Serif 4 from the `@fontsource/source-serif-4` npm package (SIL Open Font License), expected in `figures/package/files/`. Install it there with `npm pack @fontsource/source-serif-4` and unpack it, or change the path in the scripts.
- **A formatted duplicate of the memo rules.** `rules_s3.txt.rtf` had the same text as `materials/coding/rules_s3.txt`.

## Done by hand, not by script

- **The 13 November memo relabels** were made directly in `s3_final.csv`, and `data/human_checks/s3_relabel_log.md` records each one. `code/s3_final.py` rebuilds the labels as they stood before those changes; `code/analysis/s3_table.py` rebuilds the table from the current file.
- **Claude's reads** of the S9 dispute statements and of Qwen's S1 replies were done by reading, not by rule. Their codes are written into `code/checks/code_s9.py` and `data/checks/qwen_s1_review.csv`, with the words behind each code.
