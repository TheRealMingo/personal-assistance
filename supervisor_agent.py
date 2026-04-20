from langchain_ollama import ChatOllama
from langchain.agents import AgentState, create_agent
from config.config import config
from subagents.subagent_tools import weather_agent_tool, exercise_agent_tool, date_and_time_agent_tool, stem_agent_tool, coder_agent_tool, task_manager_agent_tool, email_agent_tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.middleware import before_model, wrap_tool_call
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.tools.tool_node import ToolCallRequest
from langgraph.runtime import Runtime as LangchainRuntime
from langchain.messages import RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command
from typing import Callable
from typing import Any
import tools.tool_usage_utils as tuu
import logging
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


llm = ChatOllama(
    model=config["supervisor_model"],
    validate_model_on_init=True,
    temperature=0,
    keep_alive="10m",
    reasoning=False # TODO: Make configurable
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
""" 

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
    """Keep only the last few messages to fit context window."""
    messages = state["messages"]

    if len(messages) <= 6:
        logging.info(f"Returning all messages. Message can is count is just {len(messages)}")
        return None  # No changes needed

    first_msg = messages[0]
    recent_messages = messages[-5:] if len(messages) % 2 == 0 else messages[-6:]
    new_messages = [first_msg] + recent_messages
    logging.info(f"Deleting messages. Only remembering the last 6 messages:\n {new_messages}")

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *new_messages
        ]
    }

agent = create_agent(
    model=llm,
    tools=[weather_agent_tool, 
           exercise_agent_tool, 
           date_and_time_agent_tool,
           stem_agent_tool,
           coder_agent_tool,
           task_manager_agent_tool,
           email_agent_tool],
    middleware=[monitor_tool, monitor_model, trim_messages],
    system_prompt=SYSTEM_PROMPT, 
    checkpointer=InMemorySaver(),)


def invoke_agent(input_txt: str, role: str = "user"):
    message =  {"messages": [{"role": role, "content": input_txt}]}
    agent_response = agent.invoke(
        message, 
        {"configurable": {"thread_id": "1"}},)
    return agent_response["messages"][-1].content

