"""Streamlit front-end for the AI code review & auto-fix pipeline.

Run locally:  streamlit run app.py
Deploy:       Streamlit Community Cloud, main file = app.py
"""

import dataclasses
import logging
import os
from pathlib import Path

import streamlit as st

from review_core import (
    AUTO_FIX_EXTENSIONS,
    DEFAULT_MODELS,
    PROVIDER_LABELS,
    PROVIDERS,
    REVIEWABLE_EXTENSIONS,
    SEVERITY_ICON,
    SEVERITY_RANK,
    ConfigurationError,
    FileReport,
    Pipeline,
    RunReport,
    Settings,
    render_json,
    render_markdown,
    unified_diff,
)

st.set_page_config(page_title="AI Code Review", page_icon="🔍", layout="wide")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ai_review.app")

# On Streamlit Community Cloud, keys live in st.secrets. Expose them as env vars so
# Settings.from_env() works the same locally (.env / shell) and in the cloud.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:  # no secrets file locally; that's fine
    pass

MAX_UPLOAD_BYTES = 200_000
SEVERITIES = list(SEVERITY_RANK)

# Models offered in the sidebar dropdown. Pick "Custom…" to type any other model name.
MODEL_OPTIONS = {
    "google": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
}
CUSTOM = "Custom…"

# Error text that means "this model is busy or unavailable, try another one".
FALLBACK_MARKERS = ("503", "429", "404", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "NOT_FOUND", "overloaded")


def is_fallback_error(exc: Exception) -> bool:
    return any(m.lower() in str(exc).lower() for m in FALLBACK_MARKERS)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def sidebar() -> tuple[Settings, bool, list[str]]:
    base = Settings.from_env()
    st.sidebar.header("Settings")

    provider = st.sidebar.selectbox(
        "LLM provider",
        PROVIDERS,
        index=PROVIDERS.index(base.provider),
        format_func=PROVIDER_LABELS.get,
    )

    options = MODEL_OPTIONS[provider] + [CUSTOM]
    preferred = base.model if provider == base.provider else DEFAULT_MODELS[provider]
    index = options.index(preferred) if preferred in options else options.index(CUSTOM)
    choice = st.sidebar.selectbox("Model", options, index=index, key=f"model-select-{provider}")
    if choice == CUSTOM:
        model = st.sidebar.text_input(
            "Custom model name", value=preferred, key=f"model-custom-{provider}"
        ).strip() or DEFAULT_MODELS[provider]
    else:
        model = choice

    use_fallback = st.sidebar.checkbox(
        "Auto-switch model if busy",
        value=True,
        help="If the chosen model returns 503/429 (overloaded) or 404, try the other models "
        "in the list automatically.",
    )
    fallbacks = [m for m in MODEL_OPTIONS[provider] if m != model] if use_fallback else []

    has_env_key = base.env_api_key(provider) is not None
    api_key = st.sidebar.text_input(
        "API key",
        type="password",
        placeholder="Using key from environment" if has_env_key else "Paste your API key",
        help="Kept in this browser session only. It is never written to disk.",
    )

    st.sidebar.divider()
    fail_on = st.sidebar.select_slider(
        "Quality gate fails at", options=SEVERITIES, value=base.fail_on
    )
    min_fix = st.sidebar.select_slider(
        "Auto-fix issues from", options=SEVERITIES, value=base.min_fix_severity
    )
    auto_fix = st.sidebar.toggle(
        "Auto-fix",
        value=True,
        help=f"Applies validated fixes. Supported: {', '.join(sorted(AUTO_FIX_EXTENSIONS))}",
    )

    settings = dataclasses.replace(
        base,
        provider=provider,
        model=model,
        api_key=api_key or None,
        fail_on=fail_on,
        min_fix_severity=min_fix,
    )
    return settings, auto_fix, fallbacks


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def collect_inputs() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    paste_tab, upload_tab = st.tabs(["Paste code", "Upload files"])

    with paste_tab:
        name = st.text_input(
            "Filename", value="snippet.py", help="The extension selects the language."
        )
        code = st.text_area("Code", height=320, placeholder="Paste code to review…")
        if code.strip():
            items.append((name.strip() or "snippet.py", code))

    with upload_tab:
        uploads = st.file_uploader(
            "Source files",
            accept_multiple_files=True,
            type=[ext.lstrip(".") for ext in sorted(REVIEWABLE_EXTENSIONS)],
        )
        for up in uploads or []:
            raw = up.getvalue()
            if len(raw) > MAX_UPLOAD_BYTES:
                st.warning(f"{up.name}: larger than {MAX_UPLOAD_BYTES // 1000} KB, skipped.")
                continue
            try:
                items.append((up.name, raw.decode("utf-8")))
            except UnicodeDecodeError:
                st.warning(f"{up.name}: not valid UTF-8, skipped.")
    return items


# --------------------------------------------------------------------------- #
# Run + results
# --------------------------------------------------------------------------- #
def process_with_fallback(pipelines: list[tuple[str, Pipeline]], name: str, code: str):
    """Try each model in order; move on only for busy/unavailable-type errors."""
    last: Exception | None = None
    for model, pipeline in pipelines:
        try:
            report, fixed_code = pipeline.process_text(name, code)
            return report, fixed_code, model
        except Exception as exc:
            last = exc
            if not is_fallback_error(exc):
                raise
            log.warning("Model %s failed for %s (%s); trying next", model, name, exc)
    assert last is not None
    raise last


def run_review(
    settings: Settings, auto_fix: bool, fallbacks: list[str], items: list[tuple[str, str]]
) -> dict | None:
    valid = []
    for n, c in items:
        if Path(n).suffix in REVIEWABLE_EXTENSIONS:
            valid.append((n, c))
        else:
            supported = ", ".join(sorted(REVIEWABLE_EXTENSIONS))
            st.error(f"{n}: unsupported file type. Use one of {supported}.")
    if not valid:
        return None

    try:
        pipelines = [
            (m, Pipeline(dataclasses.replace(settings, model=m), fix=auto_fix))
            for m in [settings.model, *fallbacks]
        ]
    except ConfigurationError as exc:
        st.error(str(exc))
        return None

    reports: list[FileReport] = []
    originals: dict[str, str] = {}
    new_code: dict[str, str] = {}
    models_used: dict[str, str] = {}
    bar = st.progress(0.0, text="Starting…")
    for i, (name, code) in enumerate(valid, start=1):
        bar.progress((i - 1) / len(valid), text=f"Reviewing {name} ({i}/{len(valid)})")
        originals[name] = code
        try:
            report, fixed_code, used = process_with_fallback(pipelines, name, code)
            models_used[name] = used
        except Exception as exc:  # keep other files' results if one fails
            log.exception("Review failed for %s", name)
            report, fixed_code = FileReport(path=name, error=f"{type(exc).__name__}: {exc}"), code
        reports.append(report)
        new_code[name] = fixed_code
    bar.empty()
    return {
        "report": RunReport(files=reports, fail_on=settings.fail_on),
        "originals": originals,
        "new_code": new_code,
        "models_used": models_used,
        "requested_model": settings.model,
    }


def render_file(report: FileReport, original: str, fixed_code: str) -> None:
    label = f"{'🛠️ ' if report.fixed else ''}{report.path}  ·  {len(report.issues)} issue(s)"
    with st.expander(label, expanded=bool(report.issues or report.error)):
        if report.error:
            st.error(report.error)
            return
        if report.summary:
            st.write(report.summary)
        if report.fixed:
            st.success(f"Auto-fixed: {report.fix_explanation}")
        if report.fix_error:
            st.warning(f"Auto-fix not applied: {report.fix_error}")

        shown = report.final_issues
        if shown:
            st.markdown("**Remaining issues**" if report.fixed else "**Issues**")
            rows = [
                {
                    "Severity": f"{SEVERITY_ICON[i.severity]} {i.severity}",
                    "Line": i.line,
                    "Category": i.category,
                    "Issue": i.message,
                    "Suggestion": i.suggestion,
                }
                for i in sorted(shown, key=lambda x: -SEVERITY_RANK[x.severity])
            ]
            st.dataframe(rows, hide_index=True)
        else:
            st.info("No remaining issues." if report.fixed else "No issues found.")

        if report.fixed:
            diff_tab, code_tab = st.tabs(["Diff", "Fixed file"])
            with diff_tab:
                st.code(unified_diff(original, fixed_code, report.path), language="diff")
            with code_tab:
                st.code(fixed_code, language=Path(report.path).suffix.lstrip(".") or "text")
            st.download_button(
                "Download fixed file",
                fixed_code,
                file_name=Path(report.path).name,
                key=f"dl-fixed-{report.path}",
            )


def render_results(result: dict) -> None:
    report: RunReport = result["report"]
    st.divider()
    st.subheader("Results")

    used = sorted(set(result.get("models_used", {}).values()))
    if used:
        requested = result.get("requested_model")
        if used == [requested]:
            st.caption(f"Model: {requested}")
        else:
            st.caption(
                f"Requested {requested}; answered by {', '.join(used)} "
                "(switched automatically because the first model was busy or unavailable)."
            )

    cols = st.columns(4)
    cols[0].metric("Files reviewed", len(report.files))
    cols[1].metric("Issues found", report.issues_found)
    cols[2].metric("Files auto-fixed", report.files_fixed)
    cols[3].metric("Issues remaining", report.issues_remaining)

    if report.gate_failed:
        st.error(f"Quality gate FAILED: issues at or above '{report.fail_on}' remain.")
    elif report.has_errors:
        st.warning(
            "Some files could not be reviewed, so this is NOT a clean result. "
            "See the error below and try again or pick another model."
        )
    else:
        st.success(f"Quality gate passed: no remaining issues at or above '{report.fail_on}'.")

    for f in report.files:
        render_file(f, result["originals"][f.path], result["new_code"][f.path])

    left, right = st.columns(2)
    left.download_button("Download report (Markdown)", render_markdown(report), "review_report.md")
    right.download_button(
        "Download report (JSON)", render_json(report), "review_report.json", "application/json"
    )


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def main() -> None:
    st.title("🔍 AI Code Review & Auto-Fix")
    st.caption(
        "LangChain-powered review with validated auto-fixes. Code is sent to the selected LLM "
        "provider, so do not submit secrets or code you are not allowed to share."
    )
    settings, auto_fix, fallbacks = sidebar()
    items = collect_inputs()

    if st.button("Run review", type="primary", disabled=not items):
        if not settings.resolved_key:
            st.error(f"Add a {settings.provider} API key in the sidebar (or in app secrets).")
        else:
            with st.spinner("Reviewing…"):
                outcome = run_review(settings, auto_fix, fallbacks, items)
            if outcome is not None:
                st.session_state["result"] = outcome

    if "result" in st.session_state:
        render_results(st.session_state["result"])


main()