from langchain.tools import tool
from yaml import dump
import tools.tool_usage_utils as tuu
from datetime import datetime
from config.config import config
from pytz import timezone
from uuid import uuid4
import googlemaps
import requests

gmaps = googlemaps.Client(key=config["google_maps_api_key"])

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# TODO: Weather tool can use Google Maps by default and fallback to Open Meteo.
@tool
def get_current_weather_tool(city: str="Chicago") -> str:
    """Get current weather for a given city. This tool cannot be used to get the weather for a specific date in the past or future. It can only be used to get the current weather for a city.
       This tool cannot be used to get the forecast. Use the "get_weather_forecast_tool" to get the forecast for a particular city.

    Args:
        city: The city to get the current weather for. If not city is given default to Chicago. 
    
    Returns:
        The weather for a given city
    """
    try:
        geocode_result = gmaps.geocode(city)
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = f"https://weather.googleapis.com/v1/currentConditions:lookup?key={config["google_maps_api_key"]}&location.latitude={lat}&location.longitude={lng}&unitsSystem=IMPERIAL"
        response = requests.get(google_weather_api_call)
        weather = response.json()
        logging.info(f"Response from current weather api (before timeZone calculation): {weather}")
        timezone_str = weather["timeZone"]["id"] #TODO: if timeZone is not here, don't break
        tz = timezone(timezone_str)
        weather["currentTime"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"Returning current weather: {weather}")
        return weather
    except Exception as e:
        logging.error(f"Error getting weather for {city}, Error: {str(e)}")
        return f"Could not retrieve weather for {city}. Error: {str(e)}"


@tool
def get_weather_forecast_tool(city: str="Chicago", days:int = 1) -> str:
    """Get the weather forecast for a Chicago for a given amount of days. 
    This tool cannot be used to get the weather for a specific date. 
    This tool cannot be used to get the current. Use the "get_current_weather_tool" to get the current weather. 
    
    Args:
        city: The city to get the current weather for. If not city is given default to Chicago. 
        days: The amount of days to get the weather forecast for. The default is one day.
    
    Returns: 
        The weather forecast for a given city
    """
    logging.info(f"Number of days enter: {days}")
    try:
        geocode_result = gmaps.geocode(city)
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = f"https://weather.googleapis.com/v1/forecast/days:lookup?key={config["google_maps_api_key"]}&location.latitude={lat}&location.longitude={lng}&unitsSystem=IMPERIAL&days={days}&pageSize=10"
        response = requests.get(google_weather_api_call)
        weather = response.json()
        logging.info(f"Response from weather forecast api: {weather}")
        relevant_weather = {}
        forecastDays = weather["forecastDays"]
        for day in forecastDays:
            # add more data later to see if the reorganization helped, maybe add wind
            date = f"{day["displayDate"]["year"]}-{day["displayDate"]["month"]}-{day["displayDate"]["day"]}"
            maxTemp = day["maxTemperature"]
            minTemp = day["minTemperature"]
            feelsLikeMaxTemp = day["feelsLikeMaxTemperature"]
            feelsLikeMinTemp = day["feelsLikeMinTemperature"]
            daytimeWeatherCondition = day["daytimeForecast"]["weatherCondition"]["description"]["text"]
            daytimePrecipitationPercent = day["daytimeForecast"]["precipitation"]["probability"]["percent"]
            daytimePrecipitationType = day["daytimeForecast"]["precipitation"]["probability"]["type"]
            daytimeUvIndex = day["daytimeForecast"]["uvIndex"]
            daytimeThunderstormProbability = day["daytimeForecast"]["thunderstormProbability"]
            nighttimeWeatherCondition = day["nighttimeForecast"]["weatherCondition"]["description"]["text"]
            nighttimePrecipitationPercent = day["nighttimeForecast"]["precipitation"]["probability"]["percent"]
            nighttimePrecipitationType = day["nighttimeForecast"]["precipitation"]["probability"]["type"]
            nighttimeUvIndex = day["nighttimeForecast"]["uvIndex"]
            nighttimeThunderstormProbability = day["nighttimeForecast"]["thunderstormProbability"]

            # TODO: Added structured output to model so things like maxTemp and feelLike don't get mixed
            relevant_weather[date] = {
                "maxTemp": maxTemp,
                "minTemp": minTemp,
                "feelsLikeMaxTemp": feelsLikeMaxTemp,
                "feelsLikeMinTemp": feelsLikeMinTemp,
                "daytimeWeatherCondition": daytimeWeatherCondition,
                "daytimePrecipitationPercent": daytimePrecipitationPercent,
                "daytimePrecipitationType": daytimePrecipitationType,
                "daytimeUvIndex": daytimeUvIndex,
                "daytimeThunderstormProbability": daytimeThunderstormProbability,
                "nighttimeWeatherCondition": nighttimeWeatherCondition,
                "nighttimePrecipitationPercent": nighttimePrecipitationPercent,
                "nighttimePrecipitationType": nighttimePrecipitationType,
                "nighttimeUvIndex": nighttimeUvIndex,
                "nighttimeThunderstormProbability": nighttimeThunderstormProbability,
            }
        logging.info(f"Returning weather forecast: {relevant_weather}")
        return relevant_weather
    except Exception as e:
        logging.error(f"Error getting weather for {city}, Error: {str(e)}")
        return f"Could not retrieve weather for {city}. Error: {str(e)}"