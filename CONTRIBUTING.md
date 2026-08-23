# Contributing

Thank you for helping build Knowledge Engine AI. This project follows
`knowledge-engine-core`'s own development philosophy: favor clear, tested,
well-documented changes over clever shortcuts, and never let the model
decide what evidence means -- see "The Seam" in `README.md` before
touching anything that synthesizes or scores evidence.

We are not optimizing for getting code written quickly. We are optimizing for
the project still being healthy in 10 years.

## Development Workflow

1. Open or choose an issue before starting non-trivial work.
2. Create a branch from `main`.
3. Make a focused change.
4. Add or update tests.
5. Run the repository preflight.
6. Open a pull request.

After the initial bootstrap, avoid committing directly to `main`. Use feature
branches and pull requests even for small changes.

## Branch Names

Use short, descriptive branch names:

- `feature/retrieval-intelligence`
- `fix/evidence-report-parsing`
- `docs/confidence-framework`
- `chore/dependency-bump`

## Commit Messages

Use Conventional Commits:

- `feat: add retrieval intelligence CLI`
- `fix: handle empty evidence-report results`
- `docs: document the confidence framework`
- `test: cover a malformed JSON response`
- `chore: bump knowledge-engine-core pin`

## Quality Preflight

Before opening or updating a Python pull request, normalize and validate it with:

```bash
poetry install
poetry run python scripts/preflight.py --fix
```

The preflight applies only Ruff's safe fixes, formats the tree, then reruns the
complete check-only sequence enforced by CI: Ruff format, Ruff lint, strict mypy,
pytest, pip-audit, and `git diff --check`. CI remains authoritative; do not weaken
or suppress a gate to make the preflight pass.

## Code Style

- Prefer readable, typed Python.
- Keep modules focused and small where practical.
- Avoid global mutable state.
- Add docstrings for public classes and functions.
- Never import `knowledge_engine` as a Python package -- shell out to `ke`
  (see `core_interface_contract.md` in `knowledge-engine-core`, and this
  project's own `docs/ai_design.md`). Never invoke `ke` via `shell=True`
  or with interpolated arguments.
- The LLM explains; it never judges. Any number presented as a
  confidence score must decompose into named, independently-inspectable
  components computed by this project's own deterministic code -- never
  a bare model-generated percentage. See `docs/ai_layer_architecture.md`
  in `knowledge-engine-core`.
- LLM inference stays local and offline (`knowledge_engine_ai/llm.py`).
  Never add a hosted-API call or an `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
  -style secret without an explicit owner decision first -- see
  `docs/ai_design.md`'s "Decision: local LLM".

## Tests

Tests should be small, deterministic, and offline. Fake `ke` subprocess
calls and fake `LocalLLM` implementations rather than shelling out to a
real corpus or loading a real model file in unit tests; reserve real
invocations for documented live-verification steps.

## Architecture Decisions

Record significant decisions in `docs/`, mirroring
`knowledge-engine-core`'s own design-doc-before-code discipline (see
`docs/ai_design.md`).
