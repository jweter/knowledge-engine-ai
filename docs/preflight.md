# Local preflight

Before opening or updating a Python pull request in `knowledge-engine-ai`, run the repository's locked CI-parity preflight from the repository root:

```bash
poetry install
poetry run python scripts/preflight.py
```

The script is intentionally non-mutating and fail-fast. It runs the same quality gates, in the same order, that the repository's `Quality` workflow enforces:

1. `ruff format --check --diff .`
2. `ruff check .`
3. `mypy knowledge_engine_ai tests`
4. `pytest`
5. `pip-audit`
6. `git diff --check`

If Ruff reports an auto-fixable problem, use the repository-pinned Ruff version rather than manually guessing its canonical layout:

```bash
poetry run ruff check --fix .
poetry run ruff format .
poetry run python scripts/preflight.py
```

CI remains the verification gate. The preflight exists to catch deterministic formatter, import-order, typing, test, dependency-audit, and diff-hygiene failures before a branch is presented as PR-ready. It does not weaken or replace CI, and it does not commit changes automatically.
