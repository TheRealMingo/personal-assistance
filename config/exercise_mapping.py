"""Mapping of exercises to muscle groups used by the Track Exercise page."""

MUSCLE_GROUPS = ["arms", "back", "chest", "core", "legs"]

EXERCISE_TO_MUSCLE_GROUP = {
    # Chest
    "Bench Press": "chest",
    "Incline Bench Press": "chest",
    "Decline Bench Press": "chest",
    "Dumbbell Press": "chest",
    "Chest Fly": "chest",
    "Push-Up": "chest",
    "Cable Crossover": "chest",

    # Back
    "Pull-Up": "back",
    "Chin-Up": "back",
    "Deadlift": "back",
    "Bent-Over Row": "back",
    "Lat Pulldown": "back",
    "Seated Cable Row": "back",
    "T-Bar Row": "back",

    # Legs
    "Squat": "legs",
    "Front Squat": "legs",
    "Lunge": "legs",
    "Leg Press": "legs",
    "Leg Curl": "legs",
    "Leg Extension": "legs",
    "Calf Raise": "legs",
    "Romanian Deadlift": "legs",
    "Running": "legs",
    "Cycling": "legs",
    "Walking": "legs",

    # Arms
    "Bicep Curl": "arms",
    "Hammer Curl": "arms",
    "Tricep Extension": "arms",
    "Tricep Pushdown": "arms",
    "Skull Crusher": "arms",
    "Shoulder Press": "arms",
    "Overhead Press": "arms",
    "Lateral Raise": "arms",
    "Front Raise": "arms",
    "Dip": "arms",

    # Core
    "Plank": "core",
    "Sit-Up": "core",
    "Crunch": "core",
    "Russian Twist": "core",
    "Leg Raise": "core",
    "Mountain Climber": "core",
    "Bicycle Crunch": "core",
}


def get_muscle_group(exercise: str) -> str:
    """Return the muscle group for an exercise, or 'full body' if unknown."""
    return EXERCISE_TO_MUSCLE_GROUP.get(exercise, "full body")


def list_exercises() -> list[str]:
    """Return the sorted list of supported exercises."""
    return sorted(EXERCISE_TO_MUSCLE_GROUP.keys())
