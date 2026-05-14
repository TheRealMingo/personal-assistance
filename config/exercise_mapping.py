"""Mapping of exercises to muscle groups used by the Track Exercise page."""

MUSCLE_GROUPS = ["arms", "back", "chest", "core", "legs"]

EXERCISE_TO_MUSCLE_GROUP = {
    # Chest
    "Chest Fly": "chest",
    "Chest Press": "chest",
    "Chest Presses": "chest",
    "Incline Chest Press": "chest",

    # Back
    "Lat Pulls": "back",
    "Lat Rows": "back",

    # Legs
    "Bridges": "legs",
    "Calf Raises": "legs",
    "Leg Curls": "legs",
    "Leg Extensions": "legs",
    "Leg Press": "legs",
    "Squats": "legs",

    # Arms
    "Bicep Curls": "arms",
    "Schwarzenegger Press": "arms",
    "Shoulder Presses": "arms",
    "Shrugs": "arms",
    "Tricep Curls": "arms",
    "Wrist Curls - Over": "arms",
    "Wrist Curls - Under": "arms",

    # Core
    "Cable Crunches": "core",
    "Crunches": "core",
    "Mountain Climbers": "core",
    "Oblique Side Bends": "core",
    "Plank": "core",
    "Push Ups": "core",
    "Russian Twists": "core",
    "Sit Ups": "core",
}


def get_muscle_group(exercise: str) -> str:
    """Return the muscle group for an exercise, or 'full body' if unknown."""
    return EXERCISE_TO_MUSCLE_GROUP.get(exercise, "full body")


def list_exercises() -> list[str]:
    """Return the sorted list of supported exercises."""
    return sorted(EXERCISE_TO_MUSCLE_GROUP.keys())
