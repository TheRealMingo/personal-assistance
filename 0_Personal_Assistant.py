import tools.tool_usage_utils as tuu
import streamlit as st
import logging
import time
import uuid
from pathlib import Path
from config.config import config
from supervisor_agent import agent, invoke_agent, stream_agent, reset_thread
from utils.browser_notifications import render_notification_bridge
from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


st.set_page_config(page_title=config["assistant-name"], page_icon="🤖")

# Pin the main block container's horizontal layout. Streamlit's "centered"
# layout calculates the main column's padding from the measured sidebar
# width, which is not yet available on the very first render — this causes
# the title and chat input to appear shifted right until the user navigates
# to another page and back. Forcing an explicit max-width + auto margins
# keeps the layout consistent from the first paint onward.
st.markdown(
    """
    <style>
    [data-testid="stMainBlockContainer"],
    [data-testid="stBottomBlockContainer"] {
        max-width: none !important;
        padding-left: 5rem !important;
        padding-right: 5rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
inject_mobile_css()

SESSION_IDLE_TIMEOUT_SECONDS = max(1, int(config["session_idle_timeout_seconds"]))


def _new_thread_id() -> str:
    return f"chat-{uuid.uuid4().hex}"


def _ensure_session_thread() -> None:
    """Initialize, idle-expire, and rotate the chat thread for this session.

    A fresh ``thread_id`` is generated on first load. If no user interaction
    happens for ``SESSION_IDLE_TIMEOUT_SECONDS`` seconds, the next interaction
    drops the previous LangGraph thread state, clears the on-screen chat
    history, and starts a brand new thread.
    """
    now = time.monotonic()
    last = st.session_state.get("last_interaction_ts")
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = _new_thread_id()
        st.session_state.last_interaction_ts = now
        return
    if last is not None and (now - last) > SESSION_IDLE_TIMEOUT_SECONDS:
        old_thread = st.session_state.thread_id
        try:
            reset_thread(old_thread)
        except Exception:  # noqa: BLE001 - best effort cleanup
            logging.exception(f"Failed to reset idle thread {old_thread}")
        st.session_state.thread_id = _new_thread_id()
        st.session_state.chat_history = []
        st.session_state.last_interaction_ts = now
        st.toast(
            f"Session was idle for over {SESSION_IDLE_TIMEOUT_SECONDS // 60} min — "
            "started a fresh conversation.",
            icon="🆕",
        )


def render_agent_message(
    message_content: str,
    download_key: str,
    file_name: str,
    reasoning: str | None = None,
    show_thinking: bool = False,
    activity_log: list[str] | None = None,
    show_decision_explainer: bool = True,
) -> None:
    download_tag = config["download_markdown_tag"]
    download_content = f"{download_tag}\n\n{message_content}"
    # Feature: Markdown rendering — use unsafe_allow_html so inline HTML
    # (e.g. tables, bold, code blocks) in agent responses renders correctly.
    st.markdown(message_content, unsafe_allow_html=True)
    # Feature: Agent Decision Explainer
    if activity_log and show_decision_explainer:
        with st.expander("🔍 How I answered this", expanded=False):
            st.markdown("**Subagents and tools called:**")
            for step in activity_log:
                st.markdown(f"- {step}")
    if reasoning and show_thinking:
        with st.expander("🧠 Show thinking", expanded=False):
            st.markdown(reasoning)
    st.download_button(
        "Download markdown",
        data=download_content,
        file_name=file_name,
        mime="text/markdown",
        key=download_key,
    )

# TODO: Separate Frontend and Backend code
# TODO: Create different agents and management system for team for the different tasks, one for exercise, weather, etc. for performace
# TODO: Create email address for agent
# TODO: Setup cron job to be reminded of things etc. 
# TODO: Math agent (add more tools that wolfram)
# TODO: Web Search agent
# TODO: News agent


st.title(config["assistant-name"])

_ensure_session_thread()

with st.sidebar:
    # Rendered inside the sidebar so the (height=0) iframe component does not
    # add visible vertical spacing above the chat area on the main page.
    render_notification_bridge()
    st.subheader("Session")
    st.caption(f"Thread: `{st.session_state.thread_id[:14]}…`")
    st.caption(
        f"Idle timeout: {SESSION_IDLE_TIMEOUT_SECONDS // 60} min "
        f"({SESSION_IDLE_TIMEOUT_SECONDS}s)"
    )
    # Fix: use key= so Streamlit owns the state; avoid value= + manual write
    # which causes the toggle to flip back on the following rerun.
    if "show_thinking" not in st.session_state:
        st.session_state.show_thinking = False
    st.toggle(
        "Show agent thinking",
        key="show_thinking",
        help="Reveal the model's reasoning trace under each assistant message.",
    )
    if "show_decision_explainer" not in st.session_state:
        st.session_state.show_decision_explainer = True
    st.toggle(
        "Show agent decisions",
        key="show_decision_explainer",
        help="Show which subagents and tools were called to answer each message.",
    )
    if st.button("Start new conversation", width='stretch'):
        try:
            reset_thread(st.session_state.thread_id)
        except Exception:  # noqa: BLE001
            logging.exception("Failed to reset thread on manual reset")
        st.session_state.thread_id = _new_thread_id()
        st.session_state.chat_history = []
        st.session_state.last_interaction_ts = time.monotonic()
        st.rerun()

# Global Search sidebar widget + modal preview (persistent across pages)
render_global_search()

# conversation_start = invoke_agent("Without calling any tools, tell me what your capabilities are and greet me nicely!")


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

    # st.session_state.chat_history.append({"role": "assistant", "content": conversation_start})

if len(st.session_state.chat_history) >= 5:
    st.session_state.chat_history = st.session_state.chat_history[3:]

for index, message in enumerate(st.session_state.chat_history):
    with st.chat_message(message['role']):
        if message["role"] == "assistant":
            render_agent_message(
                message["content"],
                download_key=f"assistant-download-{index}",
                file_name=f"agent-response-{index + 1}.md",
                reasoning=message.get("reasoning"),
                show_thinking=st.session_state.show_thinking,
                activity_log=message.get("activity_log"),
                show_decision_explainer=st.session_state.show_decision_explainer,
            )
        else:
            st.markdown(message['content'])

# ------------------------------------------------------------------
# Feature: Quick-Action Chips — shown only when the chat is empty
# ------------------------------------------------------------------
_QUICK_ACTIONS = [
    "What's the weather today?",
    "What's my morning routine?",
    "Show my task list",
    "Show my shopping list",
    "What time is it?",
    "Search the web for latest news",
]

if not st.session_state.chat_history:
    st.markdown("**Quick actions — tap to get started:**")
    chip_cols = st.columns(3)
    for chip_idx, chip_label in enumerate(_QUICK_ACTIONS):
        if chip_cols[chip_idx % 3].button(chip_label, key=f"chip_{chip_idx}", use_container_width=True):
            st.session_state["_chip_prompt"] = chip_label
            st.rerun()

# Apply a chip prompt that was selected on the previous rerun.
_chip_prompt = st.session_state.pop("_chip_prompt", None)

prompt = st.chat_input("Say Something")
# Merge chip prompt with typed prompt (chip takes priority when no typed input).
prompt = prompt or _chip_prompt
if prompt:
    st.session_state.last_interaction_ts = time.monotonic()
    with st.chat_message("user"):
        st.markdown(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})

    if prompt.lower() in {"tool_usage", "tool usage"}:
        st.markdown(f"Tool usage count: {tuu.tool_usage_counter}")
    else:
        with st.chat_message("assistant"):
            thinking_placeholder = st.empty()
            response_placeholder = st.empty()

            reasoning_buf = ""
            content_buf = ""
            activity_log: list[str] = []
            final_response = ""
            error_message = ""

            def _render_thinking() -> None:
                sections: list[str] = []
                if reasoning_buf:
                    sections.append(f"**Reasoning**\n\n{reasoning_buf}")
                if activity_log:
                    sections.append(
                        "**Activity**\n\n" + "\n".join(f"- {line}" for line in activity_log)
                    )
                if content_buf:
                    sections.append(f"**Drafting response**\n\n{content_buf}")
                body = "\n\n".join(sections) if sections else "_Working..._"
                with thinking_placeholder.container():
                    with st.expander("🤔 Thinking...", expanded=True):
                        st.markdown(body)

            _render_thinking()

            try:
                for event_type, payload in stream_agent(
                    prompt, thread_id=st.session_state.thread_id
                ):
                    if event_type == "reasoning":
                        reasoning_buf += payload
                        _render_thinking()
                    elif event_type == "content":
                        content_buf += payload
                        _render_thinking()
                    elif event_type == "tool_start":
                        activity_log.append(f"Calling tool: `{payload}`")
                        _render_thinking()
                    elif event_type == "tool_end":
                        if payload:
                            activity_log.append(f"Tool finished: `{payload}`")
                            _render_thinking()
                    elif event_type == "error":
                        error_message = payload
                    elif event_type == "final":
                        final_response = payload or content_buf
            except Exception as exc:  # noqa: BLE001
                logging.exception("Streaming failed; falling back to invoke_agent")
                error_message = ""
                final_response = invoke_agent(
                    prompt, thread_id=st.session_state.thread_id
                )

            # Hide the live thinking trace once the assistant is done.
            thinking_placeholder.empty()

            display_text = error_message or final_response or content_buf

            # Build a combined "thinking" trace for after-the-fact viewing.
            stored_reasoning_parts: list[str] = []
            if reasoning_buf:
                stored_reasoning_parts.append(f"**Reasoning**\n\n{reasoning_buf}")
            if activity_log:
                stored_reasoning_parts.append(
                    "**Activity**\n\n" + "\n".join(f"- {line}" for line in activity_log)
                )
            stored_reasoning = "\n\n".join(stored_reasoning_parts) or None

            with response_placeholder.container():
                render_agent_message(
                    display_text,
                    download_key=f"assistant-download-live-{len(st.session_state.chat_history)}",
                    file_name="agent-response-latest.md",
                    reasoning=stored_reasoning,
                    show_thinking=st.session_state.show_thinking,
                    activity_log=activity_log or None,
                    show_decision_explainer=st.session_state.show_decision_explainer,
                )
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": display_text,
                    "reasoning": stored_reasoning,
                    "activity_log": activity_log or None,
                }
            )
            st.session_state.last_interaction_ts = time.monotonic()

