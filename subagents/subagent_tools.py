from subagents.subagent_creation import weather_agent, exercise_agent, date_and_time_agent, stem_agent, coder_agent, task_manager_agent, email_agent, cta_bus_agent, cta_train_agent, daily_routine_agent, shopping_list_agent, web_search_agent, book_agent

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
    logging.info(f"Exercise agent called with prompt: {prompt}")
    result = exercise_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    logging.info(f"Exercise agent returns: {result['messages'][-1].content}")
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
    logging.info(f"Date/Time agent called with prompt: {prompt}")
    result = date_and_time_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    logging.info(f"Date/Time agent returns: {result['messages'][-1].content}")
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
    logging.info(f"STEM agent called with prompt: {prompt}")
    result = stem_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    logging.info(f"STEM agent returns: {result['messages'][-1].content}")
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
    logging.info(f"Coder agent returns: {result['messages'][-1].content}")
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


@tool
def shopping_list_agent_tool(prompt: str) -> str:
    """
    Shopping List agent manages the user's shopping list. Capabilities include:
        - Creating a new shopping list item
        - Deleting a shopping list item
        - Marking a shopping list item as bought
        - Updating fields on an existing item (description, url, price, category, bought)
        - Viewing all shopping list items
        - Viewing shopping list items filtered by category

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - confirmation or list of shopping list items related to the user prompt
    """
    logging.info(f"Shopping List agent called with prompt: {prompt}")
    result = shopping_list_agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )
    return result["messages"][-1].content


@tool
def web_search_agent_tool(prompt: str) -> str:
    """
    Web Search agent searches the web and extracts page content. Capabilities include:
        - Searching the web for up-to-date information on any topic
        - Extracting content from a specific URL
        - Finding websites relevant to the user's query

    Uses Tavily Search as the primary provider with Brave Search as fallback.

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - web search results or extracted page content
    """
    logging.info(f"Web Search agent called with prompt: {prompt}")
    result = web_search_agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )
    return result["messages"][-1].content


@tool
def book_agent_tool(prompt: str) -> str:
    """
    Book agent manages the user's reading list. Capabilities include:
        - Adding a new book (with title, author, genre, notes, status)
        - Updating a book's reading status
        - Updating any field on an existing book
        - Listing all books or filtering by status
        - Deleting a book from the reading list

    Valid statuses: "To Be Read", "Currently Reading", "Read", "Did not finish".

    Args:
        - prompt: the exact prompt from the user

    Returns:
        - confirmation or list of books related to the user prompt
    """
    logging.info(f"Book agent called with prompt: {prompt}")
    result = book_agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )
    return result["messages"][-1].content
