import tools.tool_usage_utils as tuu
import streamlit as st
import logging
from config.config import config
from supervisor_agent import agent, invoke_agent
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


st.set_page_config(page_title=config["assistant-name"], page_icon="🤖")

def render_agent_message(message_content: str, download_key: str, file_name: str) -> None:
    download_tag = config["download_markdown_tag"]
    download_content = f"{download_tag}\n\n{message_content}"
    st.markdown(message_content)
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
# conversation_start = invoke_agent("Without calling any tools, tell me what your capabilities are and greet me nicely!")

if st.button("Track Exercise"):
    st.switch_page("pages/track_exercise.py")



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
            )
        else:
            st.markdown(message['content'])

prompt = st.chat_input("Say Something")
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})

    if prompt.lower() in {"tool_usage", "tool usage"}:
        st.markdown(f"Tool usage count: {tuu.tool_usage_counter}")
    else:
        with st.chat_message("assistant"):
            with st.spinner("Assistant is thinking ..."):
                response = invoke_agent(prompt)
                render_agent_message(
                    response,
                    download_key=f"assistant-download-live-{len(st.session_state.chat_history)}",
                    file_name="agent-response-latest.md",
                )
                st.session_state.chat_history.append({"role": "assistant", "content": response})