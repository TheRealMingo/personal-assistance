"""
Cron agent: build and email weather, task, and CTA favorite reports.

Usage:
    python cron_agent.py --recipient you@example.com --report weather --city Chicago
    python cron_agent.py --recipient you@example.com --report tasks
    python cron_agent.py --recipient you@example.com --report buses
    python cron_agent.py --recipient you@example.com --report trains
    python cron_agent.py --recipient you@example.com --report all --city Chicago

Schedule with crontab, e.g. every day at 7 AM:
    0 7 * * * cd /path/to/peronsal-assistance && .venv/bin/python cron_agent.py --recipient you@example.com --report all --city Chicago
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from langchain_ollama import ChatOllama
from config.config import config
from config.runtime_settings import load_settings
from tools.email_tool import send_email_tool
from tools.obsidian_tool import list_incomplete_tasks_tool
from tools.weather_tool import get_current_weather_tool
from tools.time_tool import get_current_datetime_tool
from tools.cta_bus_tool import DATA_DIR as BUS_DATA_DIR, get_bus_predictions_for_stop_tool
from tools.cta_train_tool import DATA_DIR as TRAIN_DATA_DIR, get_train_arrivals_for_station_tool
from tools.daily_routine_tool import (
    get_todays_routine_status_tool,
    list_incomplete_routine_items_tool,
)

logging.basicConfig(
    filename="cron_agent.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

llm = ChatOllama(
    model=config["sub_agent_smart_model"],
    temperature=0,
    keep_alive=(
        config["sub_agents_keep_alive"] if config["sub_agents_has_keep_alive"] else "0m"
    ),
)

BUS_FAVORITES_PATH = BUS_DATA_DIR / "cta_favorite_stops.json"
TRAIN_FAVORITES_PATH = TRAIN_DATA_DIR / "cta_favorite_stations.json"


def build_weather_summary(city: str) -> str:
    logging.info(f"Fetching weather for {city}")
    weather_result = get_current_weather_tool.invoke({"city": city})
    weather_result["currentTime"] = get_current_datetime_tool.invoke({"city": city})
    weather_text = json.dumps(weather_result, indent=2, default=str) if isinstance(weather_result, dict) else str(weather_result)
  
    prompt = (
        f"Summarize the following weather data for {city} into a short, friendly report "
        f"using imperial units. Include temperature, feels like, conditions, humidity, and wind.\n\n"
        f"Format report using html, do not wrap html in markdown fences."
        f"{weather_text}"
    )
    summary = llm.invoke(prompt).content
    logging.info(f"Weather summary generated for {city}")
    return summary


def build_task_summary() -> str:
    logging.info("Fetching incomplete tasks")
    tasks_result = list_incomplete_tasks_tool.invoke({})

    if isinstance(tasks_result, str):
        return tasks_result
   
    for task in tasks_result:
        del task['Project']
        del task['Date Created']
        del task['tags']
        del task['Completed']

    # After all the deletes all that should be let is 'Task','Due Date', 'Priority'
    tasks_text = json.dumps(tasks_result, indent=2, default=str)

    prompt = (
        "Show these tasks formatted as a html table. Do not wrap html in markdown fences."
        f"{tasks_text}"
    )

    summary = llm.invoke(prompt).content
    logging.info("Task summary generated")
    return summary


def _load_favorites(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning(f"Could not read favorites at {path}: {exc}")
        return []


def build_favorite_buses_summary() -> str:
    favs = _load_favorites(BUS_FAVORITES_PATH)
    if not favs:
        return "<p><em>No favorite bus stops saved.</em></p>"

    logging.info(f"Fetching predictions for {len(favs)} favorite bus stops")
    enriched: list[dict[str, Any]] = []
    for fav in favs:
        payload: dict[str, Any] = {"stop_id": fav["stop_id"]}
        if fav.get("route"):
            payload["route"] = fav["route"]
        try:
            result = get_bus_predictions_for_stop_tool.invoke(payload)
        except Exception as exc:
            logging.warning(f"Bus favorite {fav.get('label')} failed: {exc}")
            result = {"error": str(exc)}
        enriched.append({"favorite": fav, "result": result})

    payload_text = json.dumps(enriched, indent=2, default=str)
    prompt = (
        "You are formatting a daily transit email. Below is JSON for the user's "
        "favorite CTA bus stops and the live predictions for each. For each "
        "favorite, render an HTML section with the favorite label as a small "
        "heading and a table of upcoming buses showing route, destination, "
        "minutes_until, and predicted_time. If a favorite has an 'error' or no "
        "predictions, say so briefly. Do not wrap the HTML in markdown fences.\n\n"
        f"{payload_text}"
    )
    summary = llm.invoke(prompt).content
    logging.info("Favorite buses summary generated")
    return summary


def build_favorite_trains_summary() -> str:
    favs = _load_favorites(TRAIN_FAVORITES_PATH)
    if not favs:
        return "<p><em>No favorite train stations saved.</em></p>"

    logging.info(f"Fetching arrivals for {len(favs)} favorite train stations")
    enriched: list[dict[str, Any]] = []
    for fav in favs:
        payload: dict[str, Any] = {"station_id": fav["station_id"]}
        if fav.get("route"):
            payload["route"] = fav["route"]
        try:
            result = get_train_arrivals_for_station_tool.invoke(payload)
        except Exception as exc:
            logging.warning(f"Train favorite {fav.get('label')} failed: {exc}")
            result = {"error": str(exc)}
        enriched.append({"favorite": fav, "result": result})

    payload_text = json.dumps(enriched, indent=2, default=str)
    prompt = (
        "You are formatting a daily transit email. Below is JSON for the user's "
        "favorite CTA 'L' train stations and the live arrivals for each. For "
        "each favorite, render an HTML section with the favorite label as a "
        "small heading and a table of upcoming trains showing route (line), "
        "destination, minutes_until (\"Due\" means arriving now), and "
        "arrival_time. If a favorite has an 'error' or no predictions, say so "
        "briefly. Do not wrap the HTML in markdown fences.\n\n"
        f"{payload_text}"
    )
    summary = llm.invoke(prompt).content
    logging.info("Favorite trains summary generated")
    return summary


def build_routine_reminder(period: str) -> str:
    """Build an HTML reminder for the morning or night routine."""
    period = period.lower()
    if period not in ("morning", "night"):
        raise ValueError("period must be 'morning' or 'night'")
    pending = list_incomplete_routine_items_tool.invoke({"period": period})
    label = "Morning" if period == "morning" else "Evening"
    return (
        f"<p>This is your {label.lower()} routine reminder.</p>"
        f"<pre style=\"font-family: -apple-system, system-ui, sans-serif;\">{pending}</pre>"
    )


def build_due_tasks_reminder(lead_minutes: int) -> str:
    """Build an HTML reminder for tasks due within ``lead_minutes`` (or overdue)."""
    from datetime import datetime, timedelta

    tasks = list_incomplete_tasks_tool.invoke({})
    if isinstance(tasks, str):
        return f"<p>{tasks}</p>"

    now = datetime.now()
    cutoff = now + timedelta(minutes=int(lead_minutes))
    upcoming: list[dict[str, Any]] = []
    for task in tasks:
        due = task.get("Due Date")
        if not due:
            continue
        try:
            due_dt = datetime.strptime(str(due), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if due_dt <= cutoff:
            upcoming.append(
                {
                    "Task": task.get("Task"),
                    "Due Date": due,
                    "Priority": task.get("Priority"),
                    "Status": "Overdue" if due_dt < now else "Due soon",
                }
            )

    if not upcoming:
        return "<p>No tasks due in the configured window. 🎉</p>"

    rows = "".join(
        f"<tr><td>{t['Task']}</td><td>{t['Due Date']}</td>"
        f"<td>{t.get('Priority','')}</td><td>{t['Status']}</td></tr>"
        for t in upcoming
    )
    return (
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<thead><tr><th>Task</th><th>Due</th><th>Priority</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Email weather, task, and CTA favorite reports."
    )
    parser.add_argument(
        "--recipient",
        required=False,
        default=None,
        help=(
            "Email address to send to. If omitted, uses 'notification_email' "
            "from data/settings.json."
        ),
    )
    parser.add_argument(
        "--report",
        choices=[
            "weather", "tasks", "buses", "trains", "both", "all",
            "morning_reminder", "evening_reminder", "due_tasks",
        ],
        default="all",
        help=(
            "Which report(s) to send. 'both' = weather + tasks (legacy). "
            "'all' = weather + tasks + favorite buses + favorite trains. "
            "'morning_reminder' / 'evening_reminder' / 'due_tasks' send "
            "reminder emails (recipient defaults to settings notification_email)."
        ),
    )
    parser.add_argument("--city", default="Chicago", help="City for weather report (default: Chicago)")
    args = parser.parse_args()

    settings = load_settings()
    recipient = args.recipient or settings.get("notification_email", "")
    if not recipient:
        raise SystemExit(
            "No recipient provided and no notification_email saved in settings."
        )

    sections = []
    subject_parts = []

    if args.report == "morning_reminder":
        sections.append(
            "<h1>Morning Routine Reminder</h1><br>" + build_routine_reminder("morning")
        )
        subject_parts.append("Morning Routine Reminder")
    elif args.report == "evening_reminder":
        sections.append(
            "<h1>Evening Routine Reminder</h1><br>" + build_routine_reminder("night")
        )
        subject_parts.append("Evening Routine Reminder")
    elif args.report == "due_tasks":
        lead = int(settings.get("task_reminder_lead_minutes", 60))
        sections.append(
            f"<h1>Tasks Due Soon (next {lead} min)</h1><br>"
            + build_due_tasks_reminder(lead)
        )
        subject_parts.append("Task Reminder")
    else:
        if args.report in ("weather", "both", "all"):
            sections.append("<h1>Weather Report</h1><br>" + build_weather_summary(args.city))
            subject_parts.append(f"Weather - {args.city}")

        if args.report in ("tasks", "both", "all"):
            sections.append("<h1>Incomplete Tasks</h1><br>" + build_task_summary())
            subject_parts.append("Incomplete Tasks")

        if args.report in ("buses", "all"):
            sections.append("<h1>Favorite Bus Stops</h1><br>" + build_favorite_buses_summary())
            subject_parts.append("Favorite Buses")

        if args.report in ("trains", "all"):
            sections.append("<h1>Favorite Train Stations</h1><br>" + build_favorite_trains_summary())
            subject_parts.append("Favorite Trains")

    body = "<br><br><hr><br><br>".join(sections)
    subject = "Daily Report: " + " | ".join(subject_parts)

    email_result = send_email_tool.invoke(
        {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "html": True
        }
    )

    logging.info(f"Email result: {email_result}")
    print(email_result)


if __name__ == "__main__":
    main()
