from langchain_ollama import ChatOllama
from langchain.agents import AgentState, create_agent
from config.config import config
from subagents.subagent_tools import weather_agent_tool, exercise_agent_tool, date_and_time_agent_tool, stem_agent_tool, coder_agent_tool, task_manager_agent_tool, email_agent_tool, cta_bus_agent_tool, cta_train_agent_tool, daily_routine_agent_tool, shopping_list_agent_tool, web_search_agent_tool, book_agent_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langchain.agents.middleware import before_model, wrap_tool_call
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.tools.tool_node import ToolCallRequest
from langgraph.runtime import Runtime as LangchainRuntime
from langchain.messages import RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command
from typing import Callable
from typing import Any
import json
import tools.tool_usage_utils as tuu
import logging
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


llm = ChatOllama(
    model=config["supervisor_model"],
    validate_model_on_init=True,
    temperature=0,
    keep_alive="10m",
    reasoning=True # TODO: Make configurable
)

SYSTEM_PROMPT = """
You are a friendly, helpful assistant that manages other assistants for the user. 
You are very intelligent but you ask your coder_agent_tool to help you with all coding related problems.
Always use the coder_agent_tool for coding and software engineering problems!
Always pass the full prompt to coder_agent_tool, never shorten or summarize it. 
When using the coder_agent_tool for a coding and software engineering problem always tell the user that you are asking for help with a coding problem. 

Always use task_manager_agent_tool to mark a task as completed.
Always use task_manager_agent_tool to complete a task.
Always use email_agent_tool for sending emails.
Always display any list as a table.


The assistances you manage are:
- weather_agent_tool: This agent handles a weather inquires
- exercise_agent_tool: This agent handles all exercise/fitness inquires and helps track the users exercises and weight.
- date_and_time_agent_tool: This agent handles all inquires related to the date and time
- stem_agent_tool: This agent handles all science, technology, engineering, and math inquires
- coder_agent_tool: This agent handles solving a coding problems, computer science problems, and software engineering problems
- task_manager_agent_tool: This agent handles everything related to managing tasks, todo list items, and sending reminders. Always display any list as a table.
- email_agent_tool: This agent handles all email sending needs including plain text, HTML formatted emails, and emails with attachments.
- cta_bus_agent_tool: This agent handles all Chicago CTA bus inquiries (predicted bus arrival times at a stop, by stop id or by route+direction+stop name; or predictions for stops near a lat/lng or address on a given route). Use this for any CTA bus question.
- cta_train_agent_tool: This agent handles all Chicago CTA 'L' train inquiries (predicted train arrival times at a station, by station id or station name; or predictions for stations near a lat/lng or address). Use this for any CTA train/rail question.
- daily_routine_agent_tool: This agent tracks the user's daily morning and night routines. Use it for any request about completing, uncompleting, listing, or reporting on routine items, or for showing today's morning/night completion percentage.
- shopping_list_agent_tool: This agent manages the user's shopping list. Use it for any request to add, delete, complete (mark as bought), update, view, or filter shopping list items.
- web_search_agent_tool: This agent searches the web and extracts page content. Use it for any request that requires up-to-date information from the internet, finding websites, or reading specific URLs.
- book_agent_tool: This agent manages the user's reading list. Use it for any request to add, update, list, or delete books. It tracks books the user wants to read, is reading, has read, or did not finish.

**Default fallback rule**: If no specific tool exists for a task, always use `web_search_agent_tool` as a fallback before answering from memory. When you do so, tell the user you are searching the web.

Loop-prevention rules (follow strictly):
- Call each subagent at most once per user turn unless the user has supplied new
  information that changes the request.
- If a subagent's response begins with "NEED_CLARIFICATION:", do NOT re-invoke
  that subagent. Forward the clarification question to the user verbatim and stop.
- If a tool result already answers the user's request, respond directly to the
  user without making another tool call.
- Calling a tool is optional. If no tool is needed, answer the user directly.
""" 

MAX_DUPLICATE_TOOL_CALLS = 1  # block on the 2nd identical call
RECURSION_LIMIT = 15

# Number of recent messages (in addition to the very first message) the
# supervisor keeps in its context window per turn. Configurable via env.
CONVERSATION_HISTORY_LIMIT = max(1, int(config["conversation_history_limit"]))

# Default LangGraph thread used by non-UI callers (e.g. cron_agent).
DEFAULT_THREAD_ID = "1"

# Per-thread tool-call history for duplicate detection.
_tool_call_history: dict[str, list[tuple[str, str]]] = {}


@wrap_tool_call
def dedupe_tool(request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
    """Short-circuit identical tool calls to break supervisor/subagent loops."""
    thread_id = "_default"
    try:
        thread_id = request.config.get("configurable", {}).get("thread_id", "_default")
    except AttributeError:
        pass

    try:
        args_key = json.dumps(request.tool_call.get("args", {}), sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_key = str(request.tool_call.get("args", {}))
    key = (request.tool_call["name"], args_key)

    history = _tool_call_history.setdefault(thread_id, [])
    recent = history[-5:]
    if recent.count(key) >= MAX_DUPLICATE_TOOL_CALLS:
        logging.warning(f"Blocking duplicate tool call: {key}")
        return ToolMessage(
            content=(
                "Duplicate tool call blocked. You have already invoked this tool "
                "with these exact arguments and received a response. Do not call "
                "it again. Either ask the user for clarification or answer them "
                "directly using the prior result."
            ),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    history.append(key)
    # Keep history bounded.
    if len(history) > 20:
        del history[: len(history) - 20]
    return handler(request)

@wrap_tool_call
def monitor_tool(request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
    logging.info(f"Executing tool: {request.tool_call['name']}")
    logging.info(f"Arguments: {request.tool_call['args']}")

    try:
        result = handler(request)
        logging.info(f"Tool completed successfully")
        return result
    except Exception as e:
        logging.info(f"Tool failed: {e}")
        raise

@wrap_model_call
def monitor_model(request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    logging.info(f"Supervisor last messages: {request.messages[-1].content}")
    try:
        result = handler(request)
        logging.info(f"Model call completed successfully")
        return result
    except Exception as e:
        logging.info(f"Tool failed: {e}")
        raise

@before_model
def trim_messages(state: AgentState, runtime: LangchainRuntime) -> dict[str, Any] | None:
    """Keep only the last few messages to fit context window.

    The number of recent messages retained is controlled by
    ``CONVERSATION_HISTORY_LIMIT`` (env: ``CONVERSATION_HISTORY_LIMIT``). The
    very first message is always preserved so the system/user intent is not
    lost.
    """
    messages = state["messages"]

    # +1 because we always also keep the very first message.
    if len(messages) <= CONVERSATION_HISTORY_LIMIT + 1:
        logging.info(
            f"Returning all messages. Message count is {len(messages)} <= limit "
            f"{CONVERSATION_HISTORY_LIMIT + 1}"
        )
        return None  # No changes needed

    first_msg = messages[0]
    # Keep an even-length tail when possible so a tool/result pair isn't split.
    tail_size = CONVERSATION_HISTORY_LIMIT
    if len(messages) % 2 != 0 and tail_size % 2 == 0:
        tail_size += 1
    recent_messages = messages[-tail_size:]
    new_messages = [first_msg] + recent_messages
    logging.info(
        f"Trimming messages. Keeping first + last {tail_size}:\n {new_messages}"
    )

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *new_messages
        ]
    }

agent_checkpointer = InMemorySaver()

agent = create_agent(
    model=llm,
    tools=[weather_agent_tool, 
           exercise_agent_tool, 
           date_and_time_agent_tool,
           stem_agent_tool,
           coder_agent_tool,
           task_manager_agent_tool,
           email_agent_tool,
           cta_bus_agent_tool,
           cta_train_agent_tool,
           daily_routine_agent_tool,
           shopping_list_agent_tool,
           web_search_agent_tool,
           book_agent_tool],
    middleware=[monitor_tool, dedupe_tool, monitor_model, trim_messages],
    system_prompt=SYSTEM_PROMPT, 
    checkpointer=agent_checkpointer,)


def reset_thread(thread_id: str) -> None:
    """Drop all checkpointed state for ``thread_id``.

    Used when a chat session has been idle past the configured timeout so the
    next interaction begins with a clean conversation.
    """
    _tool_call_history.pop(thread_id, None)
    deleter = getattr(agent_checkpointer, "delete_thread", None)
    if callable(deleter):
        try:
            deleter(thread_id)
            return
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logging.exception(f"delete_thread failed for {thread_id}")
    # Fallback: best-effort manual cleanup of the in-memory storage maps.
    for attr in ("storage", "writes", "blobs"):
        store = getattr(agent_checkpointer, attr, None)
        if isinstance(store, dict):
            store.pop(thread_id, None)


def invoke_agent(input_txt: str, role: str = "user", thread_id: str = DEFAULT_THREAD_ID):
    message =  {"messages": [{"role": role, "content": input_txt}]}
    # Reset duplicate-call tracking at the start of every user turn so that
    # legitimately repeating a tool across turns is allowed.
    _tool_call_history.clear()
    try:
        agent_response = agent.invoke(
            message,
            {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
        )
    except GraphRecursionError:
        logging.warning("Supervisor hit recursion limit; returning fallback message.")
        return (
            "I got stuck trying to answer that. Could you rephrase or provide "
            "more details so I can try again?"
        )
    return agent_response["messages"][-1].content


def stream_agent(input_txt: str, role: str = "user", thread_id: str = DEFAULT_THREAD_ID):
    """Stream agent execution.

    Yields tuples of ``(event_type, payload)`` where ``event_type`` is one of:

    - ``"reasoning"``: payload is a string chunk of model thinking/reasoning
      content (e.g. from a model with a thinking mode like qwen3).
    - ``"content"``: payload is a string chunk of normal model output.
    - ``"tool_start"``: payload is the tool name being invoked.
    - ``"tool_end"``: payload is the tool name that just finished.
    - ``"final"``: payload is the final assistant response string.
    - ``"error"``: payload is an error message string.
    """
    from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

    message = {"messages": [{"role": role, "content": input_txt}]}
    _tool_call_history.clear()

    # Track AI message chunks per message id so we can reconstruct the final
    # supervisor response after streaming completes.
    ai_buffers: dict[str, str] = {}
    last_ai_id: str | None = None

    def _extract_reasoning(chunk_obj: Any) -> str:
        kwargs = getattr(chunk_obj, "additional_kwargs", None) or {}
        for key in ("reasoning_content", "reasoning", "thinking"):
            value = kwargs.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    def _extract_text(chunk_obj: Any) -> str:
        content = getattr(chunk_obj, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    text_val = part.get("text")
                    if isinstance(text_val, str):
                        parts.append(text_val)
            return "".join(parts)
        return ""

    try:
        for chunk, _metadata in agent.stream(
            message,
            {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
            stream_mode="messages",
        ):
            if isinstance(chunk, (AIMessageChunk, AIMessage)):
                msg_id = getattr(chunk, "id", None) or "unknown"

                reasoning = _extract_reasoning(chunk)
                if reasoning:
                    yield "reasoning", reasoning

                text = _extract_text(chunk)
                if text:
                    ai_buffers[msg_id] = ai_buffers.get(msg_id, "") + text
                    last_ai_id = msg_id
                    yield "content", text

                tool_call_chunks = getattr(chunk, "tool_call_chunks", None) or []
                for tc in tool_call_chunks:
                    name = tc.get("name") if isinstance(tc, dict) else None
                    if name:
                        yield "tool_start", name
                if not tool_call_chunks:
                    for tc in getattr(chunk, "tool_calls", None) or []:
                        name = tc.get("name") if isinstance(tc, dict) else None
                        if name:
                            yield "tool_start", name
            elif isinstance(chunk, ToolMessage):
                yield "tool_end", getattr(chunk, "name", "") or ""
    except GraphRecursionError:
        logging.warning("Supervisor hit recursion limit; returning fallback message.")
        yield "error", (
            "I got stuck trying to answer that. Could you rephrase or provide "
            "more details so I can try again?"
        )
        return

    final_text = ai_buffers.get(last_ai_id, "") if last_ai_id else ""
    if not final_text:
        # Fallback: pull final assistant message from the checkpointed state.
        try:
            state = agent.get_state({"configurable": {"thread_id": thread_id}})
            messages = state.values.get("messages", []) if state else []
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    final_text = msg.content if isinstance(msg.content, str) else _extract_text(msg)
                    if final_text:
                        break
        except Exception:  # noqa: BLE001 - best-effort fallback
            logging.exception("Failed to retrieve final state after streaming")
    yield "final", final_text

