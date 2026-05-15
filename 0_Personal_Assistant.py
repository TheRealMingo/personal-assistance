import tools.tool_usage_utils as tuu
import streamlit as st
import logging
import time
import uuid
from config.config import config
from supervisor_agent import agent, invoke_agent, stream_agent, reset_thread
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


st.set_page_config(page_title=config["assistant-name"], page_icon="🤖")

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
) -> None:
    download_tag = config["download_markdown_tag"]
    download_content = f"{download_tag}\n\n{message_content}"
    st.markdown(message_content)
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
    st.subheader("Session")
    st.caption(f"Thread: `{st.session_state.thread_id[:14]}…`")
    st.caption(
        f"Idle timeout: {SESSION_IDLE_TIMEOUT_SECONDS // 60} min "
        f"({SESSION_IDLE_TIMEOUT_SECONDS}s)"
    )
    show_thinking = st.toggle(
        "Show agent thinking",
        value=st.session_state.get("show_thinking", False),
        help="Reveal the model's reasoning trace under each assistant message.",
    )
    st.session_state.show_thinking = show_thinking
    if st.button("Start new conversation", use_container_width=True):
        try:
            reset_thread(st.session_state.thread_id)
        except Exception:  # noqa: BLE001
            logging.exception("Failed to reset thread on manual reset")
        st.session_state.thread_id = _new_thread_id()
        st.session_state.chat_history = []
        st.session_state.last_interaction_ts = time.monotonic()
        st.rerun()

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
                show_thinking=show_thinking,
            )
        else:
            st.markdown(message['content'])

prompt = st.chat_input("Say Something")
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
                    show_thinking=show_thinking,
                )
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": display_text,
                    "reasoning": stored_reasoning,
                }
            )
            st.session_state.last_interaction_ts = time.monotonic()

