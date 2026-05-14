"""Schema for the Daily Routine Tracker.

Field names MUST match the keys used in the existing Obsidian per-day notes
exactly (case + spacing), because the Obsidian Base view reads those keys.
"""

MORNING_ITEMS: list[str] = [
    "Dynamic Stretching",
    "Eat Breakfast",
    "Plan Daily Tasks",
    "Read Bible",
    "Drink Water",
    "Shower",
    "Apply Lotion",
    "Brush Teeth in the Morning",
    "Morning Strength Training",
]

NIGHT_ITEMS: list[str] = [
    "Static Stretches",
    "Pack Bag for Tomorrow",
    "Pick Clothes for Tomorrow",
    "Review Work Calendar",
    "Review Personal Calendar",
    "Review Weekly Tasks",
    "Journal",
    "Put TV Remotes Back",
    "Put Keys, Wallet, Work Id Together",
    "Eye Mask & Eye Drops",
    "Put Dishes Away",
    "Put Food Trays Away",
    "Brush Teeth At Night",
    "Night Strength Training",
]

ALL_ITEMS: list[str] = MORNING_ITEMS + NIGHT_ITEMS

DEFAULT_TAGS: list[str] = ["#daily-routine", "#routine", "#personal-assistant"]


def normalize_item(name: str) -> str | None:
    """Case/whitespace-insensitive lookup that returns the canonical name.

    Returns None if the name is not a recognized routine item.
    """
    target = " ".join(name.strip().lower().split())
    for canonical in ALL_ITEMS:
        if " ".join(canonical.lower().split()) == target:
            return canonical
    return None


def period_of(item: str) -> str:
    """Return 'morning' or 'night' for a canonical item name."""
    if item in MORNING_ITEMS:
        return "morning"
    if item in NIGHT_ITEMS:
        return "night"
    raise ValueError(f"Unknown routine item: {item}")


def empty_routine_payload(date_iso: str) -> dict:
    """Build the YAML-ready dict for a brand-new day note (all items False)."""
    payload: dict = {"Date": date_iso, "tags": list(DEFAULT_TAGS)}
    for item in ALL_ITEMS:
        payload[item] = False
    return payload
