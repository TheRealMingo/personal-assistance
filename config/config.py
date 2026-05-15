import os
from dotenv import load_dotenv

load_dotenv(override=True)


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


config = {
    "assistant-name": os.getenv("ASSISTANT_NAME", "Mingo's Personal Assistant"),
    "download_markdown_tag": os.getenv("DOWNLOAD_MARKDOWN_TAG", "#mingo-personal-assistant"),
    "timezone": os.getenv("TIMEZONE", "America/Chicago"),
    "supervisor_model": os.getenv("SUPERVISOR_MODEL", "qwen3:1.7b"),
    "sub_agent_basic_model": os.getenv("SUB_AGENT_BASIC_MODEL", "qwen3:1.7b"),
    "sub_agent_smart_model": os.getenv("SUB_AGENT_SMART_MODEL", "qwen2.5:3b"),
    "sub_agent_small_model": os.getenv("SUB_AGENT_SMALL_MODEL", "qwen3.5:0.8b"),
    "sub_agent_tech_model": os.getenv("SUB_AGENT_TECH_MODEL", "qwen2.5-coder:3b"),
    "sub_agents_has_keep_alive": _str_to_bool(os.getenv("SUB_AGENTS_HAS_KEEP_ALIVE"), default=False),
    "sub_agents_keep_alive": os.getenv("SUB_AGENTS_KEEP_ALIVE", "5m"),
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
    # Personal Assistant chat session: idle (in seconds) after which the chat
    # thread + history is rotated/cleared on the next interaction.
    "session_idle_timeout_seconds": int(os.getenv("SESSION_IDLE_TIMEOUT_SECONDS", "1800")),
    # Maximum number of recent conversation messages (in addition to the very
    # first message) the supervisor keeps in context per turn.
    "conversation_history_limit": int(os.getenv("CONVERSATION_HISTORY_LIMIT", "5")),
    # Default city used by weather UI/tools when no browser location is shared
    # and no city is explicitly provided.
    "default_weather_location": os.getenv("DEFAULT_WEATHER_LOCATION", "Chicago"),
}
