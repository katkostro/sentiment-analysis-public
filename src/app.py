"""
Streamlit chat UI for the Sentiment Analysis Foundry Agent.

Run:
  streamlit run src/app.py
"""

from __future__ import annotations

import json
import io
import os

# Load .env from project root so the app works regardless of how it's launched
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import sys
import time

import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ToolOutput

# Ensure src/ is on path so language_tools is importable
sys.path.insert(0, os.path.dirname(__file__))


# ─── Excel reader ──────────────────────────────────────────────────────

_RESPONSE_COLS = ["response", "comment", "feedback", "text", "answer", "remarks", "survey"]
# Patterns that indicate an ID/code column — skip during auto-detection
_SKIP_COL_PATTERNS = ["id", "code", "ref", "key", "num", "date", "time", "score", "rating"]


def _load_dataframe(file_bytes: bytes) -> "pd.DataFrame":
    """Try every supported format and return a DataFrame."""
    import pandas as pd

    errors = []
    for engine in ["openpyxl", "xlrd"]:
        try:
            return pd.read_excel(io.BytesIO(file_bytes), engine=engine)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
        except Exception as exc:
            errors.append(f"csv/{enc}: {exc}")
    try:
        tables = __import__("pandas").read_html(io.BytesIO(file_bytes))
        if tables:
            return tables[0]
    except Exception as exc:
        errors.append(f"html: {exc}")

    drm_hint = ""
    if file_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        try:
            import olefile
            ole = olefile.OleFileIO(io.BytesIO(file_bytes))
            streams = [s for entry in ole.listdir() for s in entry]
            if "EncryptedPackage" in streams or "DRMEncryptedDataSpace" in streams:
                drm_hint = (
                    "\n\n**This file is protected by Microsoft Information Protection (DRM).**\n"
                    "To use it:\n"
                    "1. Open it in Excel\n"
                    "2. Go to **File \u2192 Save As** and save as a new `.xlsx` or CSV file\n"
                    "3. Upload the new unprotected file"
                )
        except Exception:
            pass
    raise ValueError("Could not open file." + drm_hint)


def _guess_text_column(df: "pd.DataFrame") -> str:
    """Pick the most likely free-text response column."""
    # 1. Column name matches a known keyword and NOT a skip pattern
    for candidate in _RESPONSE_COLS:
        for c in df.columns:
            col_lower = str(c).lower()
            if candidate in col_lower and not any(p in col_lower for p in _SKIP_COL_PATTERNS):
                return c
    # 2. Fall back: string column with longest average text length
    str_cols = df.select_dtypes(include="object").columns.tolist()
    if str_cols:
        return max(str_cols, key=lambda c: df[c].dropna().astype(str).str.len().mean())
    return str(df.columns[0])


def read_excel_responses(file_bytes: bytes, filename: str, col: str | None = None):
    """Load file and return (df, selected_col, all_columns)."""
    df = _load_dataframe(file_bytes)
    all_cols = [str(c) for c in df.columns]
    if col is None or col not in all_cols:
        col = _guess_text_column(df)
    # Normalise column name to string
    df.columns = all_cols
    return df, col, all_cols


# ─── Page configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Survey Sentiment Agent",
    page_icon="📊",
    layout="wide",
)

# ─── Load agent config ────────────────────────────────────────────────────────

@st.cache_resource
def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "agent_config.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource
def get_client(endpoint: str) -> AIProjectClient:
    return AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())


# ─── Session state ────────────────────────────────────────────────────────────

def init_session(client: AIProjectClient) -> None:
    if "thread_id" not in st.session_state:
        thread = client.agents.threads.create()
        st.session_state.thread_id = thread.id
        st.session_state.messages = []  # [{role, content}]


def reset_thread(client: AIProjectClient) -> None:
    thread = client.agents.threads.create()
    st.session_state.thread_id = thread.id
    st.session_state.messages = []
    st.success("New conversation started.")


# ─── SDK tool-call loop ──────────────────────────────────────────────────────

def _execute_sdk_tool_calls(run, client: AIProjectClient, thread_id: str):
    """Handle requires_action by executing Language SDK function tools."""
    from language_tools import TOOL_DISPATCH

    tool_outputs = []
    for call in run.required_action.submit_tool_outputs.tool_calls:
        fn_name = call.function.name
        fn_args = json.loads(call.function.arguments or "{}")
        try:
            fn = TOOL_DISPATCH.get(fn_name)
            if fn is None:
                result = json.dumps({"error": f"Unknown tool: {fn_name}"})
            else:
                result = fn(**fn_args)
        except Exception as exc:  # noqa: BLE001
            result = json.dumps({"error": str(exc)})
        tool_outputs.append(ToolOutput(tool_call_id=call.id, output=result))

    return client.agents.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run.id,
        tool_outputs=tool_outputs,
    )


def _wait_for_run(client: AIProjectClient, thread_id: str, run) -> object:
    """Poll run to completion, handling SDK function tool calls. Times out after 5 min."""
    terminal = {"completed", "failed", "cancelled", "expired"}
    deadline = time.time() + 300  # 5 minute hard timeout
    while run.status not in terminal:
        if time.time() > deadline:
            # Cancel the hung run and return a synthetic failure
            try:
                client.agents.runs.cancel(thread_id=thread_id, run_id=run.id)
            except Exception:
                pass
            run._data["status"] = "failed"
            run._data["last_error"] = {"code": "timeout", "message": "Run exceeded 5-minute timeout and was cancelled."}
            return run
        time.sleep(2)
        run = client.agents.runs.get(thread_id=thread_id, run_id=run.id)
        if run.status == "requires_action":
            run = _execute_sdk_tool_calls(run, client, thread_id)
    return run


def _retry_send(client: AIProjectClient, agent_id: str, thread_id: str, tool_mode: str) -> object:
    """Create and run the agent, retrying on rate-limit errors with backoff."""
    import re
    max_retries = 5
    for attempt in range(max_retries):
        if tool_mode == "mcp":
            run = client.agents.runs.create_and_process(thread_id=thread_id, agent_id=agent_id)
        else:
            run = client.agents.runs.create(thread_id=thread_id, agent_id=agent_id)
            run = _wait_for_run(client, thread_id, run)

        if run.status != "failed":
            return run

        err = run.last_error or {}
        code = err.get("code", "")
        msg = err.get("message", "")
        if code != "rate_limit_exceeded":
            return run   # non-rate-limit failure — return as-is

        # Parse retry-after from the message, e.g. "retry after 52 seconds"
        wait = 60
        match = re.search(r'retry after (\d+) second', msg, re.IGNORECASE)
        if match:
            wait = int(match.group(1))

        if attempt < max_retries - 1:
            st.toast(f"Rate limit hit — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
            # Sleep in small increments so Streamlit doesn't appear completely frozen
            slept = 0
            while slept < wait:
                chunk = min(5, wait - slept)
                time.sleep(chunk)
                slept += chunk
        
    return run  # return last failed run after all retries


# ─── Agent interaction ────────────────────────────────────────────────────────

def _cancel_active_runs(client: AIProjectClient, thread_id: str) -> None:
    """Cancel any runs that are still in a non-terminal state on this thread."""
    terminal = {"completed", "failed", "cancelled", "expired"}
    try:
        runs = client.agents.runs.list(thread_id=thread_id)
        for run in runs:
            if run.status not in terminal:
                try:
                    client.agents.runs.cancel(thread_id=thread_id, run_id=run.id)
                    # Wait briefly for the cancellation to take effect
                    for _ in range(10):
                        time.sleep(1)
                        r = client.agents.runs.get(thread_id=thread_id, run_id=run.id)
                        if r.status in terminal:
                            break
                except Exception:
                    pass
    except Exception:
        pass


def send_message(
    client: AIProjectClient,
    agent_id: str,
    thread_id: str,
    content: str,
    tool_mode: str = "sdk",
) -> str:
    # Ensure no active run is blocking the thread before posting
    _cancel_active_runs(client, thread_id)

    client.agents.messages.create(thread_id=thread_id, role="user", content=content)

    run = _retry_send(client, agent_id, thread_id, tool_mode)

    if run.status == "failed":
        return f"\u274c Run failed: {run.last_error}"

    last = client.agents.messages.get_last_message_text_by_role(
        thread_id=thread_id,
        role="assistant",
    )
    return last.text.value if last else "(no response)"


# ─── UI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    config = load_config()
    tool_mode = config.get("tool_mode", "sdk")
    client = get_client(config["endpoint"])
    init_session(client)

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("📊 Survey Analysis")
        st.caption(f"Agent: `{config['agent_name']}`")
        st.caption(f"Model: `{config['model']}`")
        st.caption(f"Tools: `{config.get('tool_mode', 'sdk').upper()}`")
        st.divider()

        st.subheader("Upload Survey File")
        uploaded_file = st.file_uploader(
            "Excel / CSV file",
            type=["xlsx", "xls", "csv"],
            help="Upload a survey file to analyse",
        )

        sel_cols = None
        file_bytes = None
        if uploaded_file:
            file_bytes = uploaded_file.read()
            try:
                df_preview, guessed_col, all_cols = read_excel_responses(file_bytes, uploaded_file.name)
            except Exception as exc:
                st.error(str(exc))
                st.stop()

            sel_cols = st.multiselect(
                "Response columns (select 1-2)",
                options=all_cols,
                default=[guessed_col],
                max_selections=2,
                help="Select one or two columns to analyze",
            )
            # Show a quick preview of the selected columns
            if sel_cols:
                for col in sel_cols:
                    preview_vals = df_preview[col].dropna().astype(str).head(2).tolist()
                    st.caption(f"**{col}**: " + " / ".join(f'"{v[:50]}"' for v in preview_vals))

        if file_bytes and sel_cols and st.button("Analyse File", type="primary", use_container_width=True):
            with st.spinner("Reading and analysing..."):
                try:
                    df_final, _, _ = read_excel_responses(file_bytes, uploaded_file.name)
                except Exception as exc:
                    st.error(f"Could not read file: {exc}")
                    st.stop()

                # Collect responses from all selected columns
                all_responses = []
                for col in sel_cols:
                    col_responses = df_final[col].dropna().astype(str).tolist()
                    all_responses.extend([(col, resp) for resp in col_responses])

                if not all_responses:
                    st.warning("No responses found in the selected columns.")
                    st.stop()

                # Cap at 100 responses to avoid huge messages / long runtimes
                MAX_RESPONSES = 100
                truncated = len(all_responses) > MAX_RESPONSES
                if truncated:
                    all_responses = all_responses[:MAX_RESPONSES]

                # Build message: header + numbered responses with column labels
                if len(sel_cols) == 1:
                    numbered = "\n".join(f"{i+1}. {resp}" for i, (_, resp) in enumerate(all_responses))
                    col_desc = f"column `{sel_cols[0]}`"
                else:
                    numbered = "\n".join(f"{i+1}. [{col}] {resp}" for i, (col, resp) in enumerate(all_responses))
                    col_desc = f"columns `{', '.join(sel_cols)}`"
                
                trunc_note = f"\n\n*Note: file has more rows — showing first {MAX_RESPONSES} only.*" if truncated else ""
                header = (
                    f"File: **{uploaded_file.name}** — {len(all_responses)} responses "
                    f"from {col_desc}"
                )
                user_msg = (
                    f"{header}{trunc_note}\n\n"
                    "Please analyse all survey responses below.\n"
                    "Use analyze_sentiment, extract_key_phrases, and recognize_entities tools — batch up to 10 responses per call.\n"
                    "Provide: overall sentiment distribution, top themes, any negative responses "
                    "requiring urgent attention, and 3 actionable recommendations.\n\n"
                    f"Responses:\n{numbered}"
                )

                st.session_state.messages.append({"role": "user", "content": user_msg})
                reply = send_message(
                    client, config["agent_id"], st.session_state.thread_id, user_msg,
                    tool_mode=tool_mode,
                )
                st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()

        st.divider()
        if st.button("🗑️ New Conversation", use_container_width=True):
            reset_thread(client)
            st.rerun()

        st.divider()
        st.caption(f"Thread: `{st.session_state.get('thread_id', '...')}`")

    # ── Main chat area ────────────────────────────────────────────────────────
    st.title("Survey Sentiment Agent")
    st.caption(
        "Powered by Azure AI Foundry · Azure Language MCP · GPT-4o"
    )

    # Render message history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Show placeholder when no messages yet
    if not st.session_state.messages:
        with st.chat_message("assistant"):
            st.markdown(
                "👋 Hi! I'm your Survey Analysis Agent. You can:\n\n"
                "- **Upload an Excel file** in the sidebar for full analysis\n"
                "- **Type a message** below — paste responses directly or ask questions\n\n"
                "Try: *'Analyse: Great service! / Very slow delivery / Best experience ever'*"
            )

    # Chat input
    if prompt := st.chat_input("Ask the agent or paste survey responses..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = send_message(
                    client, config["agent_id"], st.session_state.thread_id, prompt,
                    tool_mode=tool_mode,
                )
            st.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
