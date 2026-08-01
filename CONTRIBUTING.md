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
5. Run the quality checks.
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

## Quality Checks

Run these before opening a pull request:

```bash
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy knowledge_engine_ai tests
poetry run pytest
```

## Code Style

- Prefer readable, typed Python.
- Keep modules focused and small where practical.
- Avoid global mutable state.
- Add docstrings for public classes and functions.
- Never import `knowledge_engine` as a Python package -- shell out to `ke`
  (see `core_interface_contract.md` in `knowledge-engine-core`, and this
  project's own `docs/ai_design.md`). Never invoke `ke` via `shell=True`
  or with interpolated arguments.
- The LLM (once one is wired in) explains; it never judges. Any number
  presented as a confidence score must decompose into named,
  independently-inspectable components computed by this project's own
  deterministic code -- never a bare model-generated percentage. See
  `docs/ai_layer_architecture.md` in `knowledge-engine-core`.

## Tests

Tests should be small, deterministic, and offline. Fake `ke` subprocess
calls rather than shelling out to a real corpus in unit tests; reserve
real invocations for documented live-verification steps.

## Architecture Decisions

Record significant decisions in `docs/`, mirroring
`knowledge-engine-core`'s own design-doc-before-code discipline (see
`docs/ai_design.md`).
