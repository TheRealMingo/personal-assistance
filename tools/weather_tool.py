from langchain.tools import tool
from yaml import dump
import tools.tool_usage_utils as tuu
from datetime import datetime, date
from config.config import config
from pytz import timezone
from uuid import uuid4
import googlemaps
import requests
from tools.api_call_tracker import record_api_call

gmaps = googlemaps.Client(key=config["google_maps_api_key"])

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_WEATHER_LOCATION = config["default_weather_location"]

# TODO: Weather tool can use Google Maps by default and fallback to Open Meteo.
@tool
def get_current_weather_tool(city: str = DEFAULT_WEATHER_LOCATION) -> str:
    """Get current weather for a given city. This tool cannot be used to get the weather for a specific date in the past or future. It can only be used to get the current weather for a city.
       This tool cannot be used to get the forecast. Use the "get_weather_forecast_tool" to get the forecast for a particular city.

    Args:
        city: The city to get the current weather for. If no city is given default to the configured DEFAULT_WEATHER_LOCATION.
    
    Returns:
        The weather for a given city
    """
    if not city:
        city = DEFAULT_WEATHER_LOCATION
    try:
        record_api_call("google_maps")
        geocode_result = gmaps.geocode(city)
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = f"https://weather.googleapis.com/v1/currentConditions:lookup?key={config['google_maps_api_key']}&location.latitude={lat}&location.longitude={lng}&unitsSystem=IMPERIAL"
        logging.info(f"Making API call to Google Weather API for current conditions: {google_weather_api_call}")
        record_api_call("google_weather")
        response = requests.get(google_weather_api_call)
        logging.info(f"Current weather API status: {response.status_code}")
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


# --- Hourly Weather Tool ---
@tool
def get_hourly_weather_tool(city: str = DEFAULT_WEATHER_LOCATION, hours: int = 24) -> str:
    """
    Get the hourly weather forecast for a city for a given number of hours (up to 240, per Google API limit).
    Args:
        city: The city to get the hourly weather for. If not provided, defaults to the configured DEFAULT_WEATHER_LOCATION.
        hours: The number of hours to get the forecast for (default 24, max 240).
    Returns:
        A list of hourly weather data dicts, or a dict with an "error" key if failed.
    """
    logging.info(f"Requested hourly weather for city: {city}, hours: {hours}")
    hours = max(1, min(int(hours), 240))
    if not city:
        city = DEFAULT_WEATHER_LOCATION
    try:
        geocode_result = gmaps.geocode(city)
        if not geocode_result:
            raise ValueError(f"Could not geocode city: {city}")
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = (
            f"https://weather.googleapis.com/v1/forecast/hours:lookup?key={config['google_maps_api_key']}"
            f"&location.latitude={lat}&location.longitude={lng}&unitsSystem=IMPERIAL&hours={hours}"
        )
        logging.info(f"Making API call to Google Weather API for hourly forecast: {google_weather_api_call}")
        response = requests.get(google_weather_api_call)
        logging.info(f"Hourly weather API status: {response.status_code}")
        if response.status_code != 200:
            raise ValueError(f"Weather API error: {response.status_code} {response.text}")
        weather = response.json()
        logging.info(f"Response from hourly weather api: {weather}")

        timezone_id = weather.get("timeZone", {}).get("id", config.get("timezone", "America/Chicago"))
        try:
            tz = timezone(timezone_id)
        except Exception:
            tz = timezone("America/Chicago")
        now = datetime.now(tz)

        hourly_data = weather.get("forecastHours", [])
        if not isinstance(hourly_data, list) or not hourly_data:
            return {"error": f"No hourly forecast data returned for {city}."}

        parsed_hours = []
        for hour in hourly_data:
            dt_fields = hour.get("displayDateTime", {})
            try:
                year = int(dt_fields["year"])
                month = int(dt_fields["month"])
                day = int(dt_fields["day"])
                hour_of_day = int(dt_fields["hours"])
                dt = datetime(year, month, day, hour_of_day, tzinfo=tz)
            except (KeyError, ValueError, TypeError):
                dt = now
            if dt < now:
                continue

            payload = {
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "temperature": (hour.get("temperature") or {}).get("degrees"),
                "feelsLike": (hour.get("feelsLikeTemperature") or {}).get("degrees"),
                "weatherCondition": hour.get("weatherCondition", {}).get("description", {}).get("text"),
                "precipitationPercent": hour.get("precipitation", {}).get("probability", {}).get("percent"),
                "precipitationType": hour.get("precipitation", {}).get("probability", {}).get("type"),
                "uvIndex": hour.get("uvIndex"),
                "thunderstormProbability": hour.get("thunderstormProbability"),
            }
            parsed_hours.append(payload)

        logging.info(f"Returning hourly weather: {parsed_hours}")
        return parsed_hours
    except Exception as e:
        logging.error(f"Error getting hourly weather for {city}, Error: {str(e)}")
        return {"error": f"Could not retrieve hourly weather for {city}. Error: {str(e)}"}


@tool
def get_weather_forecast_tool(city: str = DEFAULT_WEATHER_LOCATION, days: int = 1) -> str:
    """Get the weather forecast for a city for a given amount of days. 
    This tool cannot be used to get the weather for a specific date. 
    This tool cannot be used to get the current. Use the "get_current_weather_tool" to get the current weather. 
    
    Args:
        city: The city to get the current weather for. If no city is given default to the configured DEFAULT_WEATHER_LOCATION.
        days: The amount of days to get the weather forecast for. The default is one day.
    
    Returns: 
        The weather forecast for a given city
    """
    logging.info(f"Number of days enter: {days}")
    # The upstream API can return prior-day entries depending on timezone cutovers.
    # Clamp requested window and keep only today + next (days-1).
    days = max(1, min(int(days), 10))
    # Request one extra day so that if the API returns a prior-day entry (which
    # we filter out below), we still end up with the requested number of
    # future days. Capped at the API's max of 10.
    api_days = min(days + 1, 10)
    if not city:
        city = DEFAULT_WEATHER_LOCATION
    try:
        geocode_result = gmaps.geocode(city)
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = f"https://weather.googleapis.com/v1/forecast/days:lookup?key={config['google_maps_api_key']}&location.latitude={lat}&location.longitude={lng}&unitsSystem=IMPERIAL&days={api_days}&pageSize=10"
        logging.info(f"Making API call to Google Weather API for forecast: {google_weather_api_call}")
        response = requests.get(google_weather_api_call)
        logging.info(f"Weather forecast API status: {response.status_code}")
        weather = response.json()
        logging.info(f"Response from weather forecast api: {weather}")

        timezone_id = weather.get("timeZone", {}).get("id", config.get("timezone", "America/Chicago"))
        tz = timezone(timezone_id)
        today_local = datetime.now(tz).date()

        relevant_weather = {}
        forecastDays = weather.get("forecastDays", [])
        parsed_days: list[tuple[date, dict]] = []

        for day in forecastDays:
            # add more data later to see if the reorganization helped, maybe add wind
            year = int(day["displayDate"]["year"])
            month = int(day["displayDate"]["month"])
            day_of_month = int(day["displayDate"]["day"])
            forecast_dt = date(year, month, day_of_month)
            if forecast_dt < today_local:
                continue

            forecast_date_key = forecast_dt.strftime("%Y-%m-%d")
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
            parsed_days.append((forecast_dt, {
                "date": forecast_date_key,
                "weekday": forecast_dt.strftime("%A"),
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
            }))

        parsed_days.sort(key=lambda item: item[0])
        for forecast_dt, payload in parsed_days[:days]:
            relevant_weather[payload["date"]] = payload

        logging.info(f"Returning weather forecast: {relevant_weather}")
        return relevant_weather
    except Exception as e:
        logging.error(f"Error getting weather for {city}, Error: {str(e)}")
        return f"Could not retrieve weather for {city}. Error: {str(e)}"


# --- Weather Alerts Tool ---
@tool
def get_weather_alerts_tool(city: str = DEFAULT_WEATHER_LOCATION) -> str:
    """Get active weather alerts for a given city using the Google Weather API.

    Args:
        city: The city to get weather alerts for. Defaults to the configured DEFAULT_WEATHER_LOCATION.

    Returns:
        A dict with an "alerts" list of active weather alerts, or an "error" key on failure.
    """
    logging.info(f"Requested weather alerts for city: {city}")
    if not city:
        city = DEFAULT_WEATHER_LOCATION
    try:
        geocode_result = gmaps.geocode(city)
        if not geocode_result:
            raise ValueError(f"Could not geocode city: {city}")
        location = geocode_result[0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        google_weather_api_call = (
            f"https://weather.googleapis.com/v1/publicAlerts:lookup?key={config['google_maps_api_key']}"
            f"&location.latitude={lat}&location.longitude={lng}&languageCode=en"
        )
        logging.info(f"Making API call to Google Weather API for alerts: {google_weather_api_call}")
        response = requests.get(google_weather_api_call)
        logging.info(f"Weather alerts API status: {response.status_code}")
        if response.status_code != 200:
            logging.warning(f"Weather Alerts API non-200: {response.status_code} {response.text}")
            return {"alerts": [], "message": f"No active weather alerts for {city}."}
        data = response.json()
        logging.info(f"Response from weather alerts api: {data}")
        # When there are no active alerts the API returns only {"regionCode": "..."} — no weatherAlerts key.
        alert_list = data.get("weatherAlerts", [])
        if not alert_list:
            return {"alerts": [], "message": f"No active weather alerts for {city}."}
        return {"alerts": alert_list}
    except Exception as e:
        logging.error(f"Error getting weather alerts for {city}, Error: {str(e)}")
        return {"error": f"Could not retrieve weather alerts for {city}. Error: {str(e)}"}
