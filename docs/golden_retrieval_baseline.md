# Golden retrieval baseline

The cross-domain retrieval benchmark is evaluated against the three reviewed Core corpora:

- `glp1` -> `data/corpora/glp1_weight_loss`
- `oncology` -> `data/corpora/oncology_nsclc_checkpoint_inhibitors`
- `mental_health` -> `data/corpora/mental_health_mdd_antidepressants`

Each corpus must provide `sources.csv` and `evidence_records.jsonl`. These remain Core-owned scientific artifacts. AI reads them only through the documented `ke evidence-report --format json` boundary.

The baseline runner must not call synthesis, use an LLM as a relevance judge, mutate Core evidence, or invent a replacement confidence score. The purpose of this milestone is measurement: establish the actual required-record and qualifier recall of the current retrieval path before changing ranking behavior.

A baseline is reproducible only when it records the Core checkout commit, AI checkout commit, retrieval limit, golden-question definitions, and per-question retrieved Evidence Record IDs. The runner therefore requires all tracked files in both the Core and AI checkouts to match their recorded commits before measurement begins. Staged or unstaged tracked changes are a hard provenance failure; untracked local output files are ignored so redirected snapshots do not invalidate their own run. Do not commit machine-specific absolute paths, credentials, local model state, or raw provider payloads.

Run the reviewed three-domain baseline from the AI environment with:

```text
ke-ai-baseline run --core-root ../knowledge-engine-core --limit 10
```

The command verifies clean tracked state in both checkouts, resolves both checkout commits with `git rev-parse HEAD`, executes Core from the explicit Core checkout root, and emits portable JSON containing the fixed question definitions and measured retrieval results. Redirect that JSON to a local file when comparing ranking experiments; only commit a snapshot when the recorded commits and reviewed corpus state are intentionally part of the experiment record.

## Compare ranking experiments

Compare a reference snapshot with a candidate snapshot using:

```text
ke-ai-baseline compare reference.json candidate.json
```

Comparison is intentionally strict. Both snapshots must use schema version 1, the same retrieval limit, and identical golden-question definitions. The command reports per-question required-record recall and qualifier-recall deltas, counts improvements and regressions, and exits non-zero when either recall metric regresses for any golden question. This makes a ranking experiment auditable without introducing an LLM judge or a replacement confidence score.

Do not compare snapshots after silently changing the golden questions or retrieval limit. Those are different benchmark definitions and require a new reference measurement.

## Hosted measurement workflow

The `Golden Retrieval Baseline` GitHub Actions workflow provides the same measurement path without depending on a developer workstation. It is intentionally manual (`workflow_dispatch`) because reconstructing the reviewed Core database and installing the full Core runtime are substantially heavier than ordinary AI quality checks.

The workflow:

1. checks out the current AI commit and current Core `main` in adjacent directories;
2. installs each repository in its own Poetry environment;
3. reconstructs `data/knowledge_engine.sqlite3` from Core's committed `data/db_parts` backup;
4. validates every database part and the reconstructed database against `manifest.json` SHA-256 and byte-count metadata;
5. invokes `ke-ai-baseline` through the real Core `ke` executable and explicit Core checkout root;
6. writes the measured recall table to the GitHub job summary; and
7. uploads `retrieval-baseline.json` as the portable experiment artifact.

The workflow does not require credentials or provider secrets and does not call external discovery providers, synthesis, or LLM judging. A measured baseline miss is data for ranking work, not a workflow failure; execution, reconstruction, provenance, or CLI failures remain hard failures.

The next ranking change should be justified by a measured miss in this baseline and should be re-evaluated against all three domains to detect regressions.
