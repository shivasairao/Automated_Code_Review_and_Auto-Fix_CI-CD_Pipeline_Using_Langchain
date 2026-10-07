# AI Code Review & Auto-Fix Pipeline

A LangChain-powered pipeline that reviews code, applies **validated** fixes, re-reviews the result,
and enforces a severity gate in CI. It ships as an installable Python package with three ways to
use it:

| Interface | Command | Use it for |
|---|---|---|
| **Streamlit app** | `streamlit run app.py` | Interactive review of pasted or uploaded files, with diffs and report downloads |
| **CLI** | `ai-review --base-ref origin/main --fix` | Local runs and CI |
| **GitHub Actions** | `.github/workflows/ai-review.yml` | Review + auto-fix commit + PR comment + required check on every pull request |

## How it works

```
                 ┌──────────────── per file ────────────────┐
 changed files → │ ruff + syntax check (hard evidence)       │
                 │        ↓                                  │
                 │ review chain  prompt | llm.with_structured_output(ReviewResult)
                 │        ↓ issues ≥ min_fix_severity        │
                 │ fix chain     prompt | llm.with_structured_output(FixResult)
                 │        ↓                                  │
                 │ validate: parses · no new lint findings · not truncated
                 │        ↓ (retry with feedback, max N)     │
                 │ run your tests → revert the fix if they fail
                 │        ↓                                  │
                 │ re-review the fixed file                  │
                 └───────────────────┬──────────────────────┘
                                     ↓
              Markdown / JSON report → severity gate → exit code
```

The gate is evaluated on what **remains after fixing**, not on the first review, so a fixed issue
doesn't fail the build.

## Project layout

```
app.py                      Streamlit UI
src/ai_review/
  config.py                 Typed settings (env / .env) via pydantic-settings
  models.py                 Pydantic models: Issue, ReviewResult, FixResult, RunReport, ...
  llm.py                    Gemini / OpenAI / Anthropic chat-model factory (timeouts, retries)
  prompts.py                Review and fix prompt templates
  analysis.py               ruff, syntax check, test runner
  reviewer.py  fixer.py     The two LangChain chains and the fix validation loop
  pipeline.py               Orchestration, revert-on-test-failure, parallel execution
  report.py                 Markdown / JSON / diff rendering
  files.py                  File discovery and git change detection
  cli.py                    `ai-review` entry point
tests/                      Offline test suite (stubbed chains, no API key)
.github/workflows/          ci.yml (this repo's CI) · ai-review.yml (the product pipeline)
Dockerfile · docker-compose.yml · Makefile · pyproject.toml · .pre-commit-config.yaml
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
make install                      # or: pip install -r requirements.txt -r requirements-dev.txt && pip install -e .
cp .env.example .env              # add GOOGLE_API_KEY (default: Gemini gemini-3.6-flash)

streamlit run app.py              # UI at http://localhost:8501
ai-review --paths examples/buggy.py            # review only
ai-review --paths examples/buggy.py --fix      # review + validated auto-fix in place
make test                                      # offline tests
```

### Docker

```bash
docker compose up --build         # reads .env, serves the UI on :8501
```

The image is multi-stage, runs as a non-root user, has a health check, and the compose file mounts
a read-only root filesystem.

## CLI reference

| Flag | Default | Description |
|---|---|---|
| `--paths P [P ...]` | | Files or directories to review |
| `--base-ref REF` | | Also review files changed vs this git ref |
| `--fix` | off | Apply validated fixes in place (Python files only) |
| `--fail-on LEVEL` | `high` | Gate threshold: `info`, `low`, `medium`, `high`, `critical` |
| `--min-fix-severity LEVEL` | `medium` | Only issues at/above this level are sent to the fixer |
| `--test-cmd CMD` | | Run after each fix (no shell); the fix is reverted if it fails |
| `--provider`, `--model` | from env | Override the LLM |
| `--report-md`, `--report-json` | `review_report.*` | Report output paths |

**Exit codes:** `0` pass · `1` gate failed (issues ≥ threshold remain) · `2` configuration/git error or a file could not be reviewed.
In GitHub Actions the report is also written to the job summary.

## Configuration

All settings come from environment variables or `.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `google` | `google`, `openai` or `anthropic` |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | | Gemini key from Google AI Studio |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | | Credentials for the other providers |
| `GOOGLE_MODEL` / `OPENAI_MODEL` / `ANTHROPIC_MODEL` | `gemini-3.6-flash` / `gpt-4o` / `claude-sonnet-5-5` | Model names |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES` | `120`, `3` | Client timeout and retry count |
| `FAIL_ON`, `MIN_FIX_SEVERITY` | `high`, `medium` | Gate and fix thresholds |
| `MAX_FILE_CHARS` | `60000` | Larger files are skipped with a note |
| `MAX_FIX_ATTEMPTS` | `3` | Fix retries before giving up |
| `MAX_WORKERS` | `4` | Parallel files (sequential whenever `--test-cmd` is used) |
| `LOG_LEVEL` | `INFO` | Python log level |

## CI/CD setup

1. Add the repository secret `GOOGLE_API_KEY` (or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` with the matching `LLM_PROVIDER` variable).
2. Optional repository variables: `LLM_PROVIDER` and `TEST_COMMAND` (for example `pytest -q`).
3. Mark the **AI Code Review & Auto-Fix / review** check as required in branch protection.

`ci.yml` lints, tests on Python 3.10–3.12, and builds the Docker image for this repository itself.
Dependabot keeps pip, Actions and Docker dependencies current.

## Security and safety design

- **Untrusted input:** code under review is passed to the model as data, and prompts instruct it to ignore instructions embedded in code.
- **Validated fixes only:** a fix must parse, introduce no new lint findings, and not be truncated, or it is retried and then discarded.
- **Revertible writes:** with `--test-cmd`, a fix that breaks your tests is restored to the original file.
- **No shell execution:** test commands are tokenised and run without a shell.
- **Secrets:** API keys are `SecretStr`, never logged, and in the UI live only in the browser session. Fork PRs are skipped in CI because GitHub withholds secrets from them.
- **Data egress:** reviewed code is sent to the configured LLM provider. Use a provider and plan that meet your data-handling requirements.

## Known limits

- Auto-fix is Python-only; other languages are review-only.
- The LLM can still propose a plausible but wrong fix. Treat bot commits like any other change and review them. Tests are the strongest safety net, so set `TEST_COMMAND`.
- Each file is reviewed in isolation, so cross-file issues are out of scope.
- Add a `LICENSE` that matches how you plan to distribute this.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow.
