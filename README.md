# 🔍 AI Code Review & Auto-Fix

> Paste or upload code, get a structured review, and receive **validated** auto-fixes you can diff and download. Built with LangChain and Streamlit. Works with Google Gemini, OpenAI and Anthropic.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-FF4B4B)](https://streamlit.io/)
[![LangChain](https://img.shields.io/badge/powered%20by-LangChain-1C3C3C)](https://www.langchain.com/)

**Live demo:** _add your Streamlit link here_

<!-- Add a screenshot: save it as docs/screenshot.png and uncomment the next line -->
<!-- ![App screenshot](docs/screenshot.png) -->

## Why this exists

LLM code reviewers are useful, but their fixes can be wrong, truncated or full of new lint errors. This project does not trust the model's first answer. Every proposed fix is checked before it is shown to you, and the quality gate is computed on what **remains after fixing**, not on the first pass.

## Features

- **Structured reviews:** severity, line number, category, message and suggestion for every issue, returned as typed Pydantic objects.
- **Validated auto-fix (Python):** a fix is accepted only if it parses, is not truncated and adds no new `ruff` findings. Rejected fixes are retried with feedback, then discarded.
- **Re-review after fixing:** the fixed file is reviewed again, and the results show what is left.
- **Quality gate:** choose the severity (`info` to `critical`) at which the run is marked failed.
- **Diff and downloads:** unified diff, the fixed file, and Markdown and JSON reports.
- **Multi-provider:** Google Gemini, OpenAI and Anthropic, with a model dropdown (Gemini 3.5, 3.6 and 3.8 Flash included) and a custom model option.
- **Auto-switch when busy:** on 503, 429 or 404 errors the app automatically tries the other models in the list.
- **Many languages:** review works for Python, JavaScript, TypeScript, Java, Go, Rust, C/C++, C#, Ruby, PHP, shell, SQL, YAML, TOML and JSON. Auto-fix is Python only.

## How it works

```
 pasted / uploaded file
          │
          ▼
 ruff + syntax check  ──► evidence passed to the model
          │
          ▼
 review chain   prompt | llm.with_structured_output(ReviewResult)
          │  issues ≥ "auto-fix from" severity
          ▼
 fix chain      prompt | llm.with_structured_output(FixResult)
          │
          ▼
 validate: parses · not truncated · no new lint findings
          │  (retry with feedback, up to 3 attempts)
          ▼
 re-review the fixed file ──► report ──► severity gate
```

## Project structure

```
app.py            Streamlit UI (inputs, sidebar, results, downloads)
review_core.py    Settings, models, LLM factory, prompts, review/fix pipeline, reports
requirements.txt  Runtime dependencies
```

`review_core.py` has no Streamlit imports, so you can reuse it from scripts or tests:

```python
from review_core import Pipeline, Settings

pipeline = Pipeline(Settings.from_env(), fix=True)
report, fixed_code = pipeline.process_text("example.py", open("example.py").read())
print(report.summary, len(report.issues))
```

## Quick start

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Provide an API key in one of three ways:

1. **Sidebar:** paste it in the app (kept in the browser session only).
2. **Environment variable:** `GOOGLE_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
3. **Secrets file:** create `.streamlit/secrets.toml`:

   ```toml
   LLM_PROVIDER = "google"
   GOOGLE_API_KEY = "your-key-here"
   ```

Then run:

```bash
streamlit run app.py
```

The app opens at <http://localhost:8501>.

## Deploy on Streamlit Community Cloud

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.
3. Select the repository, branch `main` and main file `app.py`.
4. Under **Advanced settings → Secrets**, paste:

   ```toml
   LLM_PROVIDER = "google"
   GOOGLE_API_KEY = "your-key-here"
   ```
5. Click **Deploy**. Every push to `main` redeploys automatically.

## Configuration

All values are optional environment variables or Streamlit secrets.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `google` | `google`, `openai` or `anthropic` |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | | Gemini key from Google AI Studio |
| `OPENAI_API_KEY` | | OpenAI key |
| `ANTHROPIC_API_KEY` | | Anthropic key |
| `GOOGLE_MODEL` / `OPENAI_MODEL` / `ANTHROPIC_MODEL` | `gemini-3.6-flash` / `gpt-4o` / `claude-sonnet-5-5` | Default model per provider |
| `FAIL_ON` | `high` | Gate threshold |
| `MIN_FIX_SEVERITY` | `medium` | Only issues at or above this level are sent to the fixer |
| `MAX_FILE_CHARS` | `60000` | Larger files are skipped |
| `MAX_FIX_ATTEMPTS` | `3` | Fix retries before giving up |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `120` / `3` | Client timeout and retries |

Model names and the dropdown lists live in `MODEL_OPTIONS` at the top of `app.py`.

## Security and safety design

- **Untrusted input:** code under review is passed to the model as data, and the prompts tell it to ignore instructions embedded in comments or strings.
- **Validated fixes only:** a fix must parse, avoid truncation and add no lint findings, or it is retried and then dropped.
- **Secrets:** keys typed in the sidebar live only in the browser session and are never written to disk. Keep `.env` and `.streamlit/secrets.toml` in `.gitignore`.
- **Data egress:** reviewed code is sent to the selected LLM provider. Do not submit secrets or code you are not allowed to share.

## Known limits

- Auto-fix supports Python only. Other languages are review-only.
- A model can still propose a fix that is plausible but wrong. Passing the checks does not prove the behaviour is unchanged, so review the diff and run your tests.
- Each file is reviewed in isolation, so cross-file issues are out of scope.
- Uploads are limited to 200 KB per file.

## Contributing

Issues and pull requests are welcome. Please run `ruff check .` and `ruff format .` before opening a PR, and do not add tests that call a real LLM provider.

## License

Add a `LICENSE` file (MIT is a common choice) and state it here.
