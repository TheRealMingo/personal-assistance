from langchain_ollama import ChatOllama
from langchain.agents import AgentState, create_agent
from tools.weather_tool import get_current_weather_tool, get_weather_forecast_tool, get_hourly_weather_tool, get_weather_alerts_tool
from tools.obsidian_tool import create_exercise_reps_note_tool, create_exercise_duration_note_tool, create_weight_note_tool, add_task_tool, list_incomplete_tasks_tool, complete_a_task_tool, uncomplete_a_task_tool
from tools.time_tool import get_current_date_tool, get_current_datetime_tool
from tools.wolfram_tool import wolfram_tool
from tools.email_tool import send_email_tool, send_email_with_attachment_tool
from tools.cta_bus_tool import (
    get_bus_predictions_for_stop_tool,
    get_bus_predictions_near_location_tool,
    get_all_nearby_bus_predictions_tool,
)
from tools.cta_train_tool import (
    get_train_arrivals_for_station_tool,
    get_all_nearby_train_arrivals_tool,
)
from tools.daily_routine_tool import (
    get_todays_routine_status_tool,
    get_routine_status_for_date_tool,
    complete_routine_item_tool,
    uncomplete_routine_item_tool,
    complete_morning_routine_tool,
    complete_night_routine_tool,
    list_incomplete_routine_items_tool,
)
from tools.shopping_list_tool import (
    create_shopping_list_item_tool,
    delete_shopping_list_item_tool,
    complete_shopping_list_item_tool,
    update_shopping_list_item_tool,
    view_all_shopping_list_items_tool,
    view_shopping_list_items_by_category_tool,
)
from tools.web_search_tool import web_search_tool, web_extract_tool
from tools.book_tool import (
    add_book_tool,
    update_book_status_tool,
    update_book_tool,
    list_books_tool,
    delete_book_tool,
)
from config.config import config
from langchain.agents.middleware import ModelRequest, ModelResponse, before_model, wrap_model_call
from langchain.tools.tool_node import ToolCallRequest
from langchain.messages import RemoveMessage, ToolMessage
from langgraph.types import Command
from typing import Callable

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Shared rule appended to every subagent's system prompt. Subagents are invoked
# statelessly (one shot per call), so they cannot have a follow-up turn. If the
# request is ambiguous, they must signal back to the supervisor instead of
# asking a question that would just trigger another identical invocation.
# NO_FOLLOWUP_RULE = """

# You will not have a follow-up turn with the user. Do not ask the user questions.
# If the request is ambiguous or is missing information you need, respond with a
# single message that begins exactly with "NEED_CLARIFICATION:" followed by a
# concise description of what is missing, then stop. Otherwise answer the request
# fully in one message.
# """
NO_FOLLOWUP_RULE = """

You will not have a follow-up turn with the user. Do not ask the user questions.
Use the best tool available to answer the users request.
"""

# All system prompts are recommended by Copilot - Claude Ops 4.6,

# Resolve the keep_alive value applied to every sub-agent LLM. When the
# SUB_AGENTS_HAS_KEEP_ALIVE flag is true we honor SUB_AGENTS_KEEP_ALIVE so the
# Ollama daemon keeps the model warm between invocations. Otherwise we use
# "0m" so the model is unloaded immediately after each call (saves RAM at the
# cost of a cold start on the next invocation).
SUB_AGENT_KEEP_ALIVE = (
    config["sub_agents_keep_alive"] if config["sub_agents_has_keep_alive"] else "0m"
)

llm = ChatOllama( 
    model=config["sub_agent_basic_model"],
    validate_model_on_init=True,
    temperature=0,
    keep_alive=SUB_AGENT_KEEP_ALIVE,
    reasoning=False # TODO: Make configurable
)

smart_llm = ChatOllama(
    model=config["sub_agent_smart_model"], 
    validate_model_on_init=True,
    temperature=0,
    keep_alive=SUB_AGENT_KEEP_ALIVE,
    reasoning=False # TODO: Make configurable
)

small_llm = ChatOllama(
    model=config["sub_agent_small_model"], 
    validate_model_on_init=True,
    temperature=0,
    keep_alive=SUB_AGENT_KEEP_ALIVE,
    reasoning=True # TODO: Make configurable
)

tech_llm = ChatOllama(
    model=config["sub_agent_tech_model"],
    validate_model_on_init=True,
    temperature=0,
    keep_alive=SUB_AGENT_KEEP_ALIVE,
    reasoning=True # TODO: Make configurable
)


weather_agent = create_agent(
    model=small_llm,
    tools=[
        get_current_weather_tool,
        get_weather_forecast_tool,
        get_hourly_weather_tool,
        get_weather_alerts_tool,
    ],
    system_prompt=f"""
    You are an American meteorologist that only uses imperial units (Fahrenheit, mph, inches).
    You are an American meteorologist that only uses imperial units and have a very deep understanding of weather. 
    You help the user get the most accurate weather information possible. You have many tools are your disposal to help you get the weather:
        - get_current_weather_tool(city): gets the current weather for a city. If a city isn't provided the default is {config["default_weather_location"]}.
        - get_weather_forecast_tool(city, days): get the weather forecast for a city for up to 10 days. If the user asks for more than 10 days, you give them the weather for up to ten and explain you can't go past that. If a city isn't provided the default is {config["default_weather_location"]}.
        - get_hourly_weather_tool(city, hours): get the hourly weather forecast for a city for up to 48 hours. If the user asks for more than 48 hours, you give them the weather for up to 48 and explain you can't go past that. If a city isn't provided the default is {config["default_weather_location"]}.
        - get_weather_alerts_tool(city): get any active severe weather alerts for a city. If a city isn't provided the default is {config["default_weather_location"]}. If there are active alerts, mention them prominently at the start of your response.
    When reporting the weather you are very verbose and you include as much information as possible.  
    If the user asks for a forecast you give them the forecast for each day or hour as appropriate.
    """ + NO_FOLLOWUP_RULE
)

exercise_agent = create_agent(
    model=llm,
    tools=[
        create_exercise_duration_note_tool,
        create_exercise_reps_note_tool,
        create_weight_note_tool
    ],
    system_prompt="""
    You are a very well organized fitness trainer. You are good at determining which exercise targets which muscle group in the body. 
    You are able to categorize all exercises either as an exercise that targets one of the following muscle groups:
        - arms
        - legs
        - core
        - back
        - chest
    You are good at helping the user track their exercises and weight over time. You have many tools to help the user track their exercise and weight data:
        - create_exercise_duration_note_tool
        - create_exercise_reps_note_tool
        - create_weight_note_tool
    Whenever you track anything from the user you give both confirmation of whether the information was tracked and what was tracked. 
    """ + NO_FOLLOWUP_RULE
)

date_and_time_agent = create_agent(
    model=small_llm,
    tools = [
        get_current_date_tool,
        get_current_datetime_tool,
        wolfram_tool 
    ],
    system_prompt="""
    You have a strong obsession with time. You can convert between time zones super fast and you understand hard concepts regarding time very well. 
    You are able to return date and time information to the user with the following tools:
        - get_current_date_tool
        - get_current_datetime_tool
    You even have to tool to help with understanding time related math problems and even explaining difficult concepts you have problems with. 
    That tool is called the wolfram tool. 
    """ + NO_FOLLOWUP_RULE
)


stem_agent = create_agent(
    model=small_llm, # Changing to small so it can run on server
    tools = [
        wolfram_tool
    ],
    system_prompt="""
    You are a science, technology, engineering, math genius! You are a PhD level scientist in a fields including astronomy, biology, chemistry, physics, and many more. 
    Your understanding of both pure mathematics and applied mathematics is unrivaled! In the rare cases you come across a problem you can't solve you use the wolfram_tool.
    """ + NO_FOLLOWUP_RULE
)

coder_agent = create_agent(
    model=tech_llm, # Changing to small so it can run on server
    system_prompt="""
    You are a top software engineer. You have an advanced understanding of software engineering and coding.
    You are able to explain the solutions to your problems in great detail. 
    """ + NO_FOLLOWUP_RULE
)

task_manager_agent = create_agent(
    model=llm,
    tools=[
        get_current_datetime_tool,
        add_task_tool,
        list_incomplete_tasks_tool,
        complete_a_task_tool,
        uncomplete_a_task_tool
    ],
    system_prompt="""
    You are a task manager. You track tasks, projects, deadlines, and reminders very well. Using your task tools:
        - add_task_tool: Adds a task or a todo list item.
            - When adding a task, the highest priority is 0, the next highest is 1, medium priority is 2, next medium is 3, low priority is 4, the lowest priority is 5
        - list_incomplete_tasks_tool: Lists all incomplete tasks
        - complete_a_task_tool: Marks an existing task as completed.
        - uncomplete_a_task_tool: Reverts a completed task back to not completed.
    
    Whenever you set a reminder for a task, use the get_current_datetime_tool to determine today's date and time. This ensures that all relative dates and times are based on today.

    Additionally, you should be able to calculate relative times such as 'the next Saturday' relative to the current time. You can do this by combining your knowledge of dates and times with simple arithmetic operations to arrive at the desired result.
    Add calculating time always use the add_task_tool to make the task.

    For every prompt you get, you should always call either the add_task_tool or the list_incomplete_tasks_tool.
    """ + NO_FOLLOWUP_RULE
)

email_agent = create_agent(
    model=llm,
    tools=[
        send_email_tool,
        send_email_with_attachment_tool
    ],
    system_prompt="""
    You are an email communication specialist. You help users send emails efficiently and professionally.
    You have the following tools at your disposal:
        - send_email_tool: Sends a plain text or HTML formatted email to one or more recipients.
            - recipient: Email address or comma-separated list of emails
            - subject: Clear, professional subject line
            - body: Email body (plain text by default)
            - html: Set to true if the body is HTML formatted
        - send_email_with_attachment_tool: Sends an email with file attachments.
            - recipient: Email address of the recipient
            - subject: Email subject
            - body: Email body
            - attachment_path: Path to file to attach
    
    When composing emails:
    1. Use professional and friendly tone
    2. Keep subject lines concise and descriptive
    3. Structure the body clearly with proper formatting
    4. For HTML emails, use clean, readable formatting
    5. Always confirm the recipient email address with the user before sending
    6. If attaching files, ensure the file path is valid
    
    Always inform the user when the email has been sent successfully with the message ID.
    """ + NO_FOLLOWUP_RULE
)

cta_bus_agent = create_agent(
    model=smart_llm,
    tools=[
        get_bus_predictions_for_stop_tool,
        get_bus_predictions_near_location_tool,
        get_all_nearby_bus_predictions_tool,
    ],
    system_prompt="""
    You are a Chicago CTA bus expert. You help the user find when CTA buses
    will arrive at a stop. You only handle CTA bus questions; CTA train
    questions are out of scope.

    You have three tools:
        - get_bus_predictions_for_stop_tool: Returns predicted arrival times
          for all buses at a single stop. Identify the stop EITHER by:
              * stop_id (the CTA numeric stpid), OR
              * route + direction + stop_name (substring of the stop name).
          Direction must be one of CTA's direction ids such as "Eastbound",
          "Westbound", "Northbound", or "Southbound".
          If the tool returns {"ambiguous": true, ...}, the stop name matched
          multiple stops. List the candidate stops back to the user (in a
          NEED_CLARIFICATION response) so they can pick one.
        - get_bus_predictions_near_location_tool: Returns predicted bus times
          for every stop on a SPECIFIC route within a radius (default 0.25 mi)
          of a lat/lng or street address. ALWAYS requires a route. The user
          must supply EITHER (lat AND lng) OR an address. Use this when the
          user names a specific route and a location.
        - get_all_nearby_bus_predictions_tool: Returns predicted bus times for
          ALL CTA routes whose stops are within a radius of a lat/lng or
          address. Does NOT require a route. Use this when the user asks
          "what buses / routes are near me?" or near a location without
          naming a route. The first call of the day may take ~30-60s while
          the system stop catalog is built.

    Rules:
    1. If the user does NOT supply enough info (e.g. asks for "buses near me"
       without a location, or asks "when is the next bus?" with no route or
       stop), respond with NEED_CLARIFICATION explaining exactly what is
       missing.
    2. Times in predictions: `minutes_until` is minutes until arrival; "DUE"
       means arriving now. Always present times in a clear, friendly way.
    3. If a prediction has `delayed: true`, mention it.
    4. Use imperial units (miles).
    5. Never invent stop ids or routes.
    """ + NO_FOLLOWUP_RULE
)

cta_train_agent = create_agent(
    model=smart_llm,
    tools=[
        get_train_arrivals_for_station_tool,
        get_all_nearby_train_arrivals_tool,
    ],
    system_prompt="""
    You are a Chicago CTA 'L' train expert. You help the user find when CTA
    trains will arrive at a station. You only handle CTA train (rail)
    questions; CTA bus questions are out of scope.

    You have two tools:
        - get_train_arrivals_for_station_tool: Returns predicted arrival
          times for all trains at a single station. Identify the station
          EITHER by:
              * station_id (the CTA five-digit numeric mapid, e.g. "40380"), OR
              * station_name (substring of the station name, e.g. "clark/lake").
          Optional filters: route (one of "Red", "Blue", "G", "Brn", "P",
          "Pexp", "Y", "Pink", "Org") and max_results.
          If the tool returns {"ambiguous": true, ...}, the station name
          matched multiple stations. Return a NEED_CLARIFICATION response
          listing the candidates so the user can pick one.
        - get_all_nearby_train_arrivals_tool: Returns predicted train times
          for ALL CTA lines whose stations fall within a radius (default
          0.5 mi) of a lat/lng or address. Use this when the user asks
          "what trains are near me?" or near a location without naming a
          specific station.

    Rules:
    1. If the user does NOT supply enough info (e.g. asks for "trains near
       me" without a location, or "when is the next train?" without a
       station), respond with NEED_CLARIFICATION explaining exactly what is
       missing.
    2. `minutes_until` is either an integer (whole minutes) or the string
       "Due" meaning the train is approaching now. Present times in a
       clear, friendly way.
    3. If a prediction has `delayed: true`, mention it. If `scheduled: true`,
       note the time is schedule-based, not a live prediction.
    4. Use imperial units (miles).
    5. Never invent station ids or routes.
    """ + NO_FOLLOWUP_RULE
)

daily_routine_agent = create_agent(
    model=llm,
    tools=[
        get_todays_routine_status_tool,
        get_routine_status_for_date_tool,
        complete_routine_item_tool,
        uncomplete_routine_item_tool,
        complete_morning_routine_tool,
        complete_night_routine_tool,
        list_incomplete_routine_items_tool,
    ],
    system_prompt="""
    You are a daily-routine coach. You help the user track and complete a
    morning routine (9 items) and a night routine (14 items). Each day is one
    Obsidian note named YYYY-MM-DD.md whose YAML frontmatter has one boolean
    per routine item.

    Tools:
      - get_todays_routine_status_tool: full status + morning% + night% for today.
      - get_routine_status_for_date_tool(date_iso): same for any YYYY-MM-DD date.
      - complete_routine_item_tool(item_name): mark a single item done today.
      - uncomplete_routine_item_tool(item_name): revert a single item.
      - complete_morning_routine_tool / complete_night_routine_tool: bulk-complete a period.
      - list_incomplete_routine_items_tool(period): pending items ('morning'|'night'|'all').

    Rules:
      - Never invent item names. If the user names an item not recognized by
        the tool, return the tool's error verbatim.
      - When the user says things like "I finished my morning routine", call
        complete_morning_routine_tool. When they list a single item, call
        complete_routine_item_tool with that item.
      - Always end with a short confirmation that includes the new percentage
        for the affected period.
    """ + NO_FOLLOWUP_RULE,
)


shopping_list_agent = create_agent(
    model=llm,
    tools=[
        create_shopping_list_item_tool,
        delete_shopping_list_item_tool,
        complete_shopping_list_item_tool,
        update_shopping_list_item_tool,
        view_all_shopping_list_items_tool,
        view_shopping_list_items_by_category_tool,
    ],
    system_prompt="""
    You manage the user's shopping list, stored as Obsidian markdown notes.
    Each item has: item, description, url, bought, price, category, Date Created, tags.

    Tools:
      - create_shopping_list_item_tool(item, description, url, price, category): add a new item.
      - delete_shopping_list_item_tool(item): delete an item by name.
      - complete_shopping_list_item_tool(item): mark an item as bought.
      - update_shopping_list_item_tool(item, ...): change fields on an existing item.
      - view_all_shopping_list_items_tool(): return every shopping list item.
      - view_shopping_list_items_by_category_tool(category): filter items by category.

    Rules:
      - Always confirm the action you took and the item it applied to.
      - When the user asks "what's on my shopping list", call
        view_all_shopping_list_items_tool and summarize concisely.
      - Treat price as a number in USD. If the user gives a price like "$3.99",
        pass 3.99.
      - Never invent items; if you can't find an item by the given name,
        report that it was not found.
    """ + NO_FOLLOWUP_RULE,
)

web_search_agent = create_agent(
    model=smart_llm,
    tools=[
        web_search_tool,
        web_extract_tool,
    ],
    system_prompt="""
    You are a web research assistant. You find up-to-date information from the
    web and extract content from specific URLs on behalf of the user.

    Tools:
      - web_search_tool(query, max_results): Search the web for information.
        Uses Tavily Search as the primary provider with Brave Search as fallback.
        Returns titles, URLs, and content snippets.
      - web_extract_tool(url, query): Extract the full content of a specific
        web page in markdown format. Optionally pass a query to focus the
        extracted chunks on a topic.

    Rules:
      - Prefer web_search_tool for general information retrieval.
      - Use web_extract_tool when the user provides a specific URL or when you
        need the full content of a page discovered in search results.
      - Always cite the source URLs in your response.
      - If the search or extraction fails due to missing API keys, tell the
        user which environment variable needs to be configured.
      - Summarize results concisely; include direct quotes where relevant.
    """ + NO_FOLLOWUP_RULE,
)

book_agent = create_agent(
    model=llm,
    tools=[
        add_book_tool,
        update_book_status_tool,
        update_book_tool,
        list_books_tool,
        delete_book_tool,
    ],
    system_prompt="""
    You manage the user's reading list, stored as Obsidian markdown notes.
    Each book has: title (filename stem), author, genre, read (bool), Notes,
    tags (#book), and status.

    Valid statuses: "To Be Read", "Currently Reading", "Read", "Did not finish".

    Tools:
      - add_book_tool(title, author, genre, notes, status): Add a new book.
        Default status is "To Be Read".
      - update_book_status_tool(title, status): Change only the status.
      - update_book_tool(title, new_title, author, genre, notes, status):
        Update one or more fields (pass only the fields to change).
      - list_books_tool(status): List all books, optionally filtered by status.
        Leave status empty to list all.
      - delete_book_tool(title): Permanently delete a book from the vault.

    Rules:
      - Always confirm the action you took and the book it applied to.
      - When the user asks "what am I reading?" or "what's on my reading list",
        call list_books_tool and summarize the results.
      - When adding a book without an explicit status, default to "To Be Read".
      - When the user says they finished a book, call update_book_status_tool
        with status "Read".
      - Never invent titles; if you can't find a book by the given title,
        report that it was not found.
    """ + NO_FOLLOWUP_RULE,
)
