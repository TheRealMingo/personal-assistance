from subagents.subagent_creation import weather_agent, exercise_agent, date_and_time_agent, stem_agent, coder_agent, task_manager_agent, email_agent, cta_bus_agent, cta_train_agent, daily_routine_agent

from langchain.tools import tool

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
def weather_agent_tool(prompt: str) -> str:
    """
    Weather agent can handle all weather inquires.

    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - weather information related to the user prompt
    """
    result = weather_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    logging.info(f"Weather agent returns: {result["messages"][-1].content}")
    return result["messages"][-1].content

@tool
def exercise_agent_tool(prompt: str) -> str:
    """
    Exercise agent can handle all exercise inquires.
    Exericse agent also can track exercise and weight information. 

    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - exercise information related to the user prompt
    """
    result = exercise_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content

@tool
def date_and_time_agent_tool(prompt: str) -> str:
    """
    Date/Time agent can handle all date and time inquires

    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - date and time information related to the user prompt
    """
    result = date_and_time_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content

@tool
def stem_agent_tool(prompt):
    """
    STEM agent can handle all science, technology, engineering, and math related inquires
    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - information related to the user prompt
    """
    result = stem_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content

@tool(return_direct=True)
def coder_agent_tool(prompt):
    """
    Coder agent can handle all software engineering and coding relating inquiries. 
    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - information related to the user prompt
    """
    logging.info(f"Coder agent called with prompt: {prompt}")
    result = coder_agent.invoke({"messages": [{"role": "user", "content": prompt},]}, 
                                {"configurable": {"thread_id": "1"}},)
    return result["messages"][-1].content


@tool
def task_manager_agent_tool(prompt):
    """
    Task Manager Agent can handle all tasks related needs. Task Manager Agent responsibilities include:
        - Adding a tasks
        - Completing a tasks
        - Sending reminders of tasks
        - Updating a task
    Args: 
        - prompt: the exact prompt from the user
    
    Returns:
        - information related to the user prompt
    """
    logging.info(f"Task Manager agent called with prompt: {prompt}")
    result = task_manager_agent.invoke({"messages": [{"role": "user", "content": prompt},]},)
    return result["messages"][-1].content


@tool
def email_agent_tool(prompt):
    """
    Email Agent can handle all email sending needs. Email Agent responsibilities include:
        - Sending plain text emails
        - Sending HTML formatted emails
        - Sending emails with attachments
        - Professional email composition
    
    Args: 
        - prompt: the exact prompt from the user (e.g., "Send an email to john@example.com with subject 'Hello' and body 'Hi there'")
    
    Returns:
        - confirmation message with email send status and message ID
    """
    logging.info(f"Email agent called with prompt: {prompt}")
    result = email_agent.invoke({"messages": [{"role": "user", "content": prompt},]},)
    return result["messages"][-1].content


@tool
def cta_bus_agent_tool(prompt: str) -> str:
    """
    CTA Bus Agent handles all Chicago CTA bus inquiries, including:
        - Predicted bus arrival/departure times for a specific bus stop
          (by stop id, or by route + direction + stop name)
        - Predicted bus arrival times for stops near a lat/lng or address
          along a given CTA route

    Only handles CTA buses (not CTA trains, not other transit agencies).

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - bus prediction information related to the user prompt
    """
    logging.info(f"CTA Bus agent called with prompt: {prompt}")
    result = cta_bus_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content


@tool
def cta_train_agent_tool(prompt: str) -> str:
    """
    CTA Train Agent handles all Chicago CTA 'L' train (rail) inquiries, including:
        - Predicted train arrival times for a specific station
          (by station id / mapid, or by station name)
        - Predicted train arrival times for all stations within a radius of
          a lat/lng or address ("trains near me")
        - Filtering arrivals by line (Red, Blue, Green, Brown, Purple,
          Purple Express, Yellow, Pink, Orange)

    Only handles CTA trains (not CTA buses, not Metra, not other transit agencies).

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - train arrival information related to the user prompt
    """
    logging.info(f"CTA Train agent called with prompt: {prompt}")
    result = cta_train_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content

@tool
def daily_routine_agent_tool(prompt: str) -> str:
    """
    Daily Routine agent tracks the user's morning (9 items) and night
    (14 items) routines, stored as one Obsidian note per day. It can read
    today's status, complete or uncomplete individual items, bulk-complete
    a whole period, and list pending items.

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - confirmation or status text related to the user's routine
    """
    logging.info(f"Daily Routine agent called with prompt: {prompt}")
    result = daily_routine_agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )
    return result["messages"][-1].content
