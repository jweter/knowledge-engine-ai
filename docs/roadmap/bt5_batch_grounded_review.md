# BT-5 grounded review batching

The fresh music/endurance BT-0 benchmark measured grounded extraction/review/promotion at roughly 171-210 seconds, making it the dominant cold-run stage.

`ke evidence-review-automate` already accepts an evidence JSONL file without `--evidence-record-id` and reviews every eligible automated record in that file under the existing Core grounding rules. The AI grounded-completion bridge previously spawned one Core process per staged EvidenceRecord.

This slice changes only orchestration: AI invokes Core's existing batch-capable command once for the bounded staged file. Core still performs the same per-record LLM-grounded PICO extraction, grounding checks, review promotion, and final durable-evidence promotion. A batch-process failure is reported fail-closed against every staged record because AI cannot safely attribute partial completion after a failed process.

Acceptance is the same untouched cold->warm music/endurance benchmark. Compare `grounded_extraction` duration and final promoted EvidenceRecord counts against the pre-change timing artifact. Evidence yield and release gates must not be weakened.
