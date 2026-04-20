"""
Cron agent: build and email weather and/or incomplete-task reports.

Usage:
    python cron_agent.py --recipient you@example.com --report weather --city Chicago
    python cron_agent.py --recipient you@example.com --report tasks
    python cron_agent.py --recipient you@example.com --report both --city Chicago

Schedule with crontab, e.g. every day at 7 AM:
    0 7 * * * cd /path/to/peronsal-assistance && .venv/bin/python cron_agent.py --recipient you@example.com --report both --city Chicago
"""

import argparse
import json
import logging

from langchain_ollama import ChatOllama
from config.config import config
from tools.email_tool import send_email_tool
from tools.obsidian_tool import list_incomplete_tasks_tool
from tools.weather_tool import get_current_weather_tool
from tools.time_tool import get_current_datetime_tool

logging.basicConfig(
    filename="cron_agent.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

llm = ChatOllama(
    model=config["sub_agent_smart_model"],
    temperature=0,
    keep_alive="0m",
)


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


def main():
    parser = argparse.ArgumentParser(description="Email weather and/or incomplete task reports.")
    parser.add_argument("--recipient", required=True, help="Email address to send to")
    parser.add_argument("--report", choices=["weather", "tasks", "both"], default="both", help="Which report to send")
    parser.add_argument("--city", default="Chicago", help="City for weather report (default: Chicago)")
    args = parser.parse_args()

    sections = []
    subject_parts = []

    if args.report in ("weather", "both"):
        sections.append("<h1>Weather Report</h1><br>" + build_weather_summary(args.city))
        subject_parts.append(f"Weather - {args.city}")

    if args.report in ("tasks", "both"):
        sections.append("<h1>Incomplete Tasks</h1><br>" + build_task_summary())
        subject_parts.append("Incomplete Tasks")

    body = "<br><br><hr><br><br>".join(sections)
    subject = "Daily Report: " + " | ".join(subject_parts)

    email_result = send_email_tool.invoke(
        {
            "recipient": args.recipient,
            "subject": subject,
            "body": body,
            "html": True
        }
    )

    logging.info(f"Email result: {email_result}")
    print(email_result)


if __name__ == "__main__":
    main()
