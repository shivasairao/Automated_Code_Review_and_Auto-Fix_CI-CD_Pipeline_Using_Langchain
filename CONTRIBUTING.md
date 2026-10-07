# Contributing

```bash
python -m venv .venv && source .venv/bin/activate
make install          # runtime + dev deps, editable install
pre-commit install    # optional: lint/format on commit
make lint test        # must pass before opening a PR
```

- Code style is enforced by `ruff` (lint + format, line length 100).
- Tests use stubbed LLM chains, so they run offline and need no API key. Keep it that way:
  never add tests that call a real provider.
- New behaviour needs a test. Prompt changes should be accompanied by a note on what failure
  mode they address.
- Keep the safety properties intact: source code stays untrusted input, fixes are validated
  before they are applied, and anything that writes files must be revertible.

## Releasing

1. Update the version in `pyproject.toml` and `src/ai_review/__init__.py`.
2. Tag `vX.Y.Z` on `main` once CI is green.
