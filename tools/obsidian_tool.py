from langchain.tools import tool
from yaml import dump, safe_load
import tools.tool_usage_utils as tuu
from datetime import datetime
from config.config import config
from pytz import timezone
from uuid import uuid4
from pathlib import Path

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# TODO: Add ability to add addition details after properties 


def create_exercise_json(exercise: str, date: str, reps_or_duration: int, sets: int, weight: float, muscle_group: str = None) -> dict:
    weight_data = f"{weight} lbs" if weight != 0 and weight != None else "bodyweight"
    exercise_data = {
        "Exercise": exercise.title(),
        "Date": date,
        "Duration / Reps": reps_or_duration,
        "Sets": sets,
        "weight": weight_data,
        "Primary Muscle Group": muscle_group,
        "tags": ["#exercise", f"#{muscle_group}", "#personal-assistant"]
    }
    return exercise_data

def create_task_json(task: str, date_created, project:str=None, due_date:str=None, priority: int= None):
    project = f"[[{project}]]" if project != None else ""
    if priority == None:
        priority = 5

    task_data = {
        "Task": task.title(),
        "Project": project,
        "Date Created": date_created,
        "Due Date": due_date,
        "priority": priority,
        "tags": ["#task", "#personal-assistant"],
        "Completed": False
    }
    return task_data

reps_exercise_schema = {
    "type": "object",
    "properties": {
        "exercise_name": {"type": "string"},
        "reps": {"type": "integer"},
        "sets": {"type": "integer"},
        "weight": {"type": "number"},
        "muscle_group": {"type": "string"},
    },
    "required": ["exercise_name", "reps", "sets", "weight", "muscle_group"],
}
@tool("create_exercise_reps_note_tool", args_schema=reps_exercise_schema)
def create_exercise_reps_note_tool(exercise_name: str, reps: int, sets: int, weight: float, muscle_group: str = None) -> str:
    """
    Do not use this tool to track duration.
    A tool to create a new exercise note that has reps in the Obsidian vault. 
    It takes the note content as input and returns a confirmation message
    
    Args:
        exercise_name (str): The name of the exercise.
        reps (int): The number of repetitions.
        sets (int): The number of sets.
        weight (float): The weight used for the exercise.
        muscle_group (str, optional): The muscle group targeted by the exercise.

    Returns:
        str: A confirmation message indicating the success of the operation.

    """
    logging.info("Creating reps based exercise note in Obsidian vault...")
    tuu.tool_usage_counter["create_exercise_note_tool"] = tuu.tool_usage_counter["create_exercise_note_tool"] + 1
    logging.debug(tuu.tool_usage_counter)
    tz = timezone(config["timezone"])
    now = datetime.now(tz)
    datetime_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    datetime_in_ms = int(now.timestamp() * 1000)
    exercise_data = create_exercise_json(exercise_name, datetime_str, reps, sets, weight, muscle_group)
    logging.info(f"Exercise data\n: {exercise_data}")
    exercise = dump(exercise_data, default_flow_style=False, sort_keys=False, indent=2)
    exercise_note_content = f"""---\n{exercise}---"""
    new_file = config["obsidian_vault_exercise_path"] + f"/Exercise-{uuid4()}-{datetime_in_ms}.md"
    with open(new_file, "w") as f:
        f.write(exercise_note_content)
    logging.info(f"Exercise note: {exercise_note_content}")
    logging.info("Exercise note created successfully!")
    return f"Exercise note created in Obsidian vault: {config['obsidian_vault_exercise_path']}  \n---  \n {exercise}---" #Streamlit requires two spaces before newline to render it



duration_exercise_schema = {
    "type": "object",
    "properties": {
        "exercise_name": {"type": "string"},
        "duration": {"type": "string", 
                     "description": "Duration shorthand: [number] hr [number] min [number] secs. Example: '1 hr 10 min 5 secs' or '0 hr 5 min 30 secs'.", 
                     "pattern": "^\\d+\\shr\\s\\d+\\smin\\s\\d+\\ssecs$"},
        "sets": {"type": "integer"},
        "weight": {"type": "number"},
        "muscle_group": {"type": "string", "default": "other"},
    },
    "required": ["exercise_name", "reps", "sets", "weight", "muscle_group"],
}
@tool("create_exercise_duration_note_tool", args_schema=duration_exercise_schema)
def create_exercise_duration_note_tool(exercise_name: str, duration: str, sets: int, weight: float, muscle_group: str = None):
    """
    Do not use this tool to track reps.
    A tool to create a new exercise note that a duration the Obsidian vault. 
    It takes the note content as input and returns a confirmation message
    
    Args:
        exercise_name (str): The name of the exercise.
        duration (int): The duration of the exercise. The duration is formatted as '[number] hr [number] min [number] secs. Example: '10 min 5 secs' or '5 min 30 secs'
        sets (int): The number of sets.
        weight (float): The weight used for the exercise.
        muscle_group (str, optional): The muscle group targeted by the exercise.

    Returns:
        str: A statement letting the user knwow there exercise has been tracked. 

    """
    logging.info("Creating an duration based exercise note in Obsidian vault...")
    logging.debug(tuu.tool_usage_counter)
    tz = timezone(config["timezone"])
    now = datetime.now(tz)
    datetime_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    datetime_in_ms = int(now.timestamp() * 1000)
    exercise_data = create_exercise_json(exercise_name, datetime_str, duration, sets, weight, muscle_group)
    logging.info(f"Exercise data\n: {exercise_data}")
    exercise = dump(exercise_data, default_flow_style=False, sort_keys=False, indent=2)
    exercise_note_content = f"""---\n{exercise}---"""
    new_file = config["obsidian_vault_exercise_path"] + f"/Exercise-{uuid4()}-{datetime_in_ms}.md"
    with open(new_file, "w") as f:
        f.write(exercise_note_content)
    logging.info(f"Exercise note: {exercise_note_content}")
    logging.info("Exercise note created successfully!")
    return f"Exercise note created in Obsidian vault: {config['obsidian_vault_exercise_path']}  \n---  \n {exercise}---" #Streamlit requires two spaces before newline to render it

@tool("create_weight_note_tool")
def create_weight_note_tool(weight: float) -> str:
    """
    Create a note to track the weight for a the user.

    Args:
        weight (float): The weight to be tracked.

    Returns:
        str: A statement letting the user knwow there exercise has been tracked. 
    """
    logging.info("Creating a weight note in Obsidian vault...")
    logging.debug(tuu.tool_usage_counter)
    tz = timezone(config["timezone"])
    now = datetime.now(tz)
    datetime_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    datetime_in_ms = int(now.timestamp() * 1000)
    weight_data = {
        "Date": datetime_str,
        "Weight": weight,
        "tags": ["#weight", "#personal-assistant"]
    }
    logging.info(f"Weight data\n: {weight_data}")
    weight = dump(weight_data, default_flow_style=False, sort_keys=False, indent=2)
    weight_note_content = f"""---\n{weight}---"""
    new_file = config["obsidian_vault_weight_path"] + f"/Weight-{uuid4()}-{datetime_in_ms}.md"
    with open(new_file, "w") as f:
        f.write(weight_note_content)
    logging.info(f"Weight note: {weight_note_content}")
    logging.info("Weight note created successfully!")
    return f"Weight note created in Obsidian vault: {config['obsidian_vault_weight_path']}  \n---  \n {weight}---" 

@tool
def add_task_tool(task: str, project:str=None, due_date:str=None, priority: int= None) -> str:
    """
    Add a new task or todo item to the list of tasks.
    Args:   
        - task: The task to be added
        - project: The project where the task belongs (optional)
        - due_date: The date when the task is due (optional). Format is "%Y-%m-%dT%H:%M:%S" example: "2023-10-05T14:30:00" is 2:30pm on October 5th, 2023
        - priority: The priority level of the task ,0 is the highest priority. Default is None.
    
    Returns: 
       A message indicating that the task or todo item has been successfully
       added to the list of tasks.
    """
    logging.info("Creatig a task item in the Obsidian vault ...")
    tz = timezone(config["timezone"])
    now = datetime.now(tz)
    date_created_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    task_data = create_task_json(task, date_created_str, project, due_date, priority)
    logging.info(f"Task data\n: {task_data}")
    task = dump(task_data, default_flow_style=False, sort_keys=False, indent=2)
    title = task_data["Task"]
    del task_data["Task"]
    task_note_content = f"""---\n{task}---"""
    new_file = config["obsidian_vault_task_list_path"] + f"/{title}.md"
    try:
        with open(new_file, "x") as f:
            f.write(task_note_content)
    except FileExistsError as e:
            return "Task already exists"

    logging.info("Task created successfully!")
    return f"Task {task} was successfully created in Obsidian vault: {new_file} \n---  \n {task}---"

@tool(return_direct=True)
def list_incomplete_tasks_tool() -> str:
    """
    Returns a list of incomplete tasks to the user.
    
    Returns: 
       A list of incomplete tasks in the Obsidian vault.
    """
    logging.info("List of all tasks in Obsidian vault ...")
    folder_path_of_tasks = Path(config["obsidian_vault_task_list_path"])
    tasks = list(folder_path_of_tasks.glob("*.md")) #Can use rglob for recursive read, to read sub directorys and the current directory
    incomplete_tasks = []
    for task in tasks:
        logging.info(f"Current reading: {task}")
        with open(task,"r") as file:
            try:
                content = "\n".join(file.readlines()[1:-1]) #Removes the first and last "---"
                content = safe_load(content)
                if content is not None and "Completed" in content and bool(content["Completed"]) == True:
                    continue
                if not "#task" in content["tags"] and not "task" in content["tags"]:
                    continue
                content["Task"] = str(file.name).split("/")[-1][:-3] #-1 gets filename from the fullpage, -2 removes extension
                incomplete_tasks.append(content)
            except Exception as e:
                logging.error(f"Unable to read file {file.name}")

    if len(incomplete_tasks) > 0:
        logging.info("Success in loading tasks!")
        return incomplete_tasks
    else:
        logging.info("No incomplete tasks were found.")
        return "No incomplete tasks were found."

@tool
def complete_a_task_tool(task: str) -> str:
    """
    Complete a task by checking the completed checkbox.

    Args:
        task: The task to be marked completed

    Returns:
        A confirmation on whether the tasks was marked completed.
    """
    logging.info("Completing a task in the Obsidian vault ...")
    task_file = config["obsidian_vault_task_list_path"] + f"/{task.title()}.md"
    content = None
    try:
        with open(task_file, "r") as file:
            try:
                content = "\n".join(file.readlines()[1:-1]) #Removes the first and last "---"
                content = safe_load(content)
                if content is not None and "Completed" in content and bool(content["Completed"]) == True:
                    logging.info("Task is already completed.")
                    return "Task is already completed."
            except Exception as e:
                logging.error(f"Error reading task: {task}\n Error {e}")
                return "Error reading task"

        content["Completed"] = True
        task_note_content = dump(content, default_flow_style=False, sort_keys=False, indent=2)
        task_note_content = f"""---\n{task_note_content}---"""
       
        with open(task_file, "w") as f:
            try:
                f.write(task_note_content)
            except Exception as e:
                logging.error(f"Error updating task: {task}\n Error {e}")
                return "Error updating task"
    except Exception as e:
        logging.error(f"Error attempting to mark task '{task}' as completed.\n Error {e}")
        return "Error attempting to mark task as completed."

    logging.info("Successfully completed task")
    return f"Successfully updated task in Obsidian vault: {task_file}"

@tool
def uncomplete_a_task_tool(task: str) -> str:
    """
    Mark a previously completed task as not completed by unchecking the
    completed checkbox.

    Args:
        task: The task to be marked as not completed.

    Returns:
        A confirmation on whether the task was marked as not completed.
    """
    logging.info("Uncompleting a task in the Obsidian vault ...")
    task_file = config["obsidian_vault_task_list_path"] + f"/{task.title()}.md"
    content = None
    try:
        with open(task_file, "r") as file:
            try:
                content = "\n".join(file.readlines()[1:-1]) #Removes the first and last "---"
                content = safe_load(content)
                if content is None:
                    logging.error(f"No content for task: {task}")
                    return "Error reading task"
                if "Completed" in content and bool(content["Completed"]) is False:
                    logging.info("Task is already not completed.")
                    return "Task is already not completed."
            except Exception as e:
                logging.error(f"Error reading task: {task}\n Error {e}")
                return "Error reading task"

        content["Completed"] = False
        if "Date Completed" in content:
            del content["Date Completed"]
        task_note_content = dump(content, default_flow_style=False, sort_keys=False, indent=2)
        task_note_content = f"""---\n{task_note_content}---"""

        with open(task_file, "w") as f:
            try:
                f.write(task_note_content)
            except Exception as e:
                logging.error(f"Error updating task: {task}\n Error {e}")
                return "Error updating task"
    except Exception as e:
        logging.error(f"Error attempting to mark task '{task}' as not completed.\n Error {e}")
        return "Error attempting to mark task as not completed."

    logging.info("Successfully uncompleted task")
    return f"Successfully updated task in Obsidian vault: {task_file}"