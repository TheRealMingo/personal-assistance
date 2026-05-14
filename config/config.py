import os
from dotenv import load_dotenv

load_dotenv(override=True)

config = {
    "assistant-name": os.getenv("ASSISTANT_NAME", "Mingo's Personal Assistant"),
    "download_markdown_tag": os.getenv("DOWNLOAD_MARKDOWN_TAG", "#mingo-personal-assistant"),
    "timezone": os.getenv("TIMEZONE", "America/Chicago"),
    "supervisor_model": os.getenv("SUPERVISOR_MODEL", "qwen3:1.7b"),
    "sub_agent_basic_model": os.getenv("SUB_AGENT_BASIC_MODEL", "qwen3:1.7b"),
    "sub_agent_smart_model": os.getenv("SUB_AGENT_SMART_MODEL", "qwen2.5:3b"),
    "sub_agent_small_model": os.getenv("SUB_AGENT_SMALL_MODEL", "qwen3.5:0.8b"),
    "sub_agent_tech_model": os.getenv("SUB_AGENT_TECH_MODEL", "qwen2.5-coder:3b"),
    "obsidian_vault_exercise_path": os.getenv("OBSIDIAN_VAULT_EXERCISE_PATH", "."),
    "obsidian_vault_weight_path": os.getenv("OBSIDIAN_VAULT_WEIGHT_PATH", "."),
    "obsidian_vault_task_list_path": os.getenv("OBSIDIAN_VAULT_TASK_LIST_PATH", "."),
    "obsidian_vault_daily_routine_path": os.getenv("OBSIDIAN_VAULT_DAILY_ROUTINE_PATH", "."),
    "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY"),
    "wolfram_alpha_spoken_api_key": os.getenv("WOLFRAM_ALPHA_SPOKEN_API_KEY"),
    "wolfram_alpha_llm_api_key": os.getenv("WOLFRAM_ALPHA_LLM_API_KEY"),
    "gmail_smtp_email": os.getenv("GMAIL_SMTP_EMAIL"),
    "gmail_smtp_app_password": os.getenv("GMAIL_SMTP_APP_PASSWORD"),
    "cta_bus_tracker_api_key": os.getenv("CTA_BUS_TRACKER_API_KEY"),
    "cta_train_tracker_api_key": os.getenv("CTA_TRAIN_TRACKER_API_KEY"),
}
