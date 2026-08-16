# Golden retrieval baseline

The cross-domain retrieval benchmark is evaluated against the three reviewed Core corpora:

- `glp1` -> `data/corpora/glp1_weight_loss`
- `oncology` -> `data/corpora/oncology_nsclc_checkpoint_inhibitors`
- `mental_health` -> `data/corpora/mental_health_mdd_antidepressants`

Each corpus must provide `sources.csv` and `evidence_records.jsonl`. These remain Core-owned scientific artifacts. AI reads them only through the documented `ke evidence-report --format json` boundary.

The baseline runner must not call synthesis, use an LLM as a relevance judge, mutate Core evidence, or invent a replacement confidence score. The purpose of this milestone is measurement: establish the actual required-record and qualifier recall of the current retrieval path before changing ranking behavior.

A baseline is reproducible only when it records the Core checkout commit, AI checkout commit, retrieval limit, golden-question definitions, and per-question retrieved Evidence Record IDs. Do not commit machine-specific absolute paths, credentials, local model state, or raw provider payloads.

The next ranking change should be justified by a measured miss in this baseline and should be re-evaluated against all three domains to detect regressions.
