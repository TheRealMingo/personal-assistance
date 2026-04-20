import datetime
from langchain.tools import tool
import tools.tool_usage_utils as tuu
import pytz
import googlemaps
from config.config import config

gmaps = googlemaps.Client(key=config["google_maps_api_key"])

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


@tool
def get_current_datetime_tool(city:str=None) -> str:
    """Get the current date and time. 
      Can optionally get the current for a specific city if enter.
    
    Args:
        city: The city to get the current date and time for. Is an optional parameter, time will default to American/Chicago if city isn't given. 

    Returns:
        The current date and time in the specified timezone.
    """
    # Convert ISO format to Python datetime
    
    
    try:
        if city == None:
            timezone = pytz.timezone(config["timezone"])
            return datetime.datetime.now(timezone)
        geocode_result = gmaps.geocode(city)
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        timezone_result = gmaps.timezone((lat, lng))
        timezone_str = timezone_result["timeZoneId"]
        timezone = pytz.timezone(timezone_str)
        current_time = datetime.datetime.now(timezone)
        return current_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")
    except pytz.UnknownTimeZoneError:
        # If the timezone is not known, return the current time
        logging.error(f"Unknown timezone: {timezone_str}. Returning current time in UTC.")
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z%z")
    except Exception as e:
        logging.error(f"Error retrieving time for {city}: {str(e)}")
        return f"Could not retrieve time for {city}. Error: {str(e)}"

@tool
def get_current_date_tool() -> str:
    """Get the current date.
    
    Returns:
        The current date in YYYY-MM-DD format.
    """
    tuu.tool_usage_counter["date_tool"] = tuu.tool_usage_counter["date_tool"] + 1
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Returning the current date: {date}")
    return datetime.datetime.now().strftime("%Y-%m-%d")