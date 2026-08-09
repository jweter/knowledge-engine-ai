"""AI-O2: the durable `ResearchSession`/`ResearchEvent` persistence layer.

See `docs/roadmap/future_ai_orchestration_plan.md`'s "Implementation
Roadmap" section: AI-O2 builds session persistence, event log,
checkpointing, and continuation, right after AI-O1's `ResearchPlan`/
`ResearchTask` contracts. Success criterion: a workflow can stop and
resume without losing or duplicating state. No orchestrator, no LLM
call, and no real workflow node connects to this yet -- that is AI-O3
(deterministic orchestrator) and later.
"""
