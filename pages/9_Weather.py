"""Weather page: current conditions + 7-day forecast for a chosen city.

Behavior:
- On load, attempts to use the browser geolocation widget to detect the
  user's current city.
- If geolocation isn't available, falls back to ``DEFAULT_WEATHER_LOCATION``
  from config / ``.env``.
- A text input lets the user override the city; the page refreshes with
  current weather + 7-day forecast for that city.
"""

from __future__ import annotations
from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search

from datetime import datetime
import logging
from typing import Any

import altair as alt
import googlemaps
import pandas as pd
import streamlit as st

from config.config import config
from tools.weather_tool import (
    DEFAULT_WEATHER_LOCATION,
    get_current_weather_tool,
    get_weather_forecast_tool,
    get_hourly_weather_tool,
    get_weather_alerts_tool,
)
from utils.browser_geolocation import render_browser_location_widget

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Weather", page_icon="⛅")
inject_mobile_css()
render_global_search()
st.title("⛅ Weather")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

st.markdown(
        """
        <style>
            .wx-current-temp {
                font-size: clamp(2.2rem, 4vw, 3.2rem);
                font-weight: 800;
                line-height: 1;
                margin: 0.1rem 0 0.4rem 0;
            }
            .wx-current-meta {
                font-size: 1.15rem;
                font-weight: 600;
            }
            .wx-current-time {
                font-size: 1.05rem;
                font-weight: 700;
                color: #0f4c81;
                background: rgba(15, 76, 129, 0.08);
                border: 1px solid rgba(15, 76, 129, 0.25);
                border-radius: 0.6rem;
                padding: 0.35rem 0.6rem;
                display: inline-block;
                margin-top: 0.25rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
)

_gmaps = googlemaps.Client(key=config["google_maps_api_key"]) if config.get("google_maps_api_key") else None


def _city_from_coords(lat: float, lng: float) -> str | None:
    """Reverse-geocode coordinates to a 'City, State' string."""
    if _gmaps is None:
        return None
    try:
        results = _gmaps.reverse_geocode((lat, lng))
    except Exception:  # noqa: BLE001
        logging.exception("Reverse geocode failed")
        return None
    if not results:
        return None
    locality = state = country = None
    for component in results[0].get("address_components", []):
        types = component.get("types", [])
        if "locality" in types and not locality:
            locality = component.get("long_name")
        elif "postal_town" in types and not locality:
            locality = component.get("long_name")
        elif "administrative_area_level_1" in types and not state:
            state = component.get("short_name")
        elif "country" in types and not country:
            country = component.get("short_name")
    parts = [p for p in (locality, state, country) if p]
    return ", ".join(parts) if parts else results[0].get("formatted_address")


def _format_temp(value: Any) -> str:
    if isinstance(value, dict):
        deg = value.get("degrees")
        unit = value.get("unit", "")
        unit_letter = "F" if "FAHRENHEIT" in str(unit).upper() else ("C" if "CELSIUS" in str(unit).upper() else "")
        if deg is not None:
            return f"{round(deg)}°{unit_letter}".strip("°")
    if isinstance(value, (int, float)):
        return f"{round(value)}°"
    return "—"


def _safe_get(d: Any, *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _weekday_from_date_key(date_key: str) -> str:
    try:
        return datetime.strptime(date_key, "%Y-%m-%d").strftime("%A")
    except (TypeError, ValueError):
        return "—"


def _render_current(weather: dict, city: str) -> None:
    if not isinstance(weather, dict) or "error" in weather:
        st.error(f"Could not load current weather for {city}.")
        st.code(str(weather))
        return

    condition = _safe_get(weather, "weatherCondition", "description", "text", default="—")
    icon_uri = _safe_get(weather, "weatherCondition", "iconBaseUri")
    temp = _format_temp(weather.get("temperature"))
    feels = _format_temp(weather.get("feelsLikeTemperature"))
    humidity = _safe_get(weather, "relativeHumidity", default="—")
    wind_speed = _safe_get(weather, "wind", "speed", "value", default="—")
    wind_unit_full = _safe_get(weather, "wind", "speed", "unit", default="")
    # Map full unit names to abbreviations
    unit_abbr_map = {
        "MILES_PER_HOUR": "mph",
        "KILOMETERS_PER_HOUR": "km/h",
        "METERS_PER_SECOND": "m/s",
        "KNOTS": "kt",
    }
    wind_unit = unit_abbr_map.get(str(wind_unit_full).upper(), str(wind_unit_full))
    wind_dir = _safe_get(weather, "wind", "direction", "cardinal", default="")
    uv = _safe_get(weather, "uvIndex", default="—")
    precip_pct = _safe_get(weather, "precipitation", "probability", "percent", default="—")
    current_time = weather.get("currentTime", "—")
    current_weekday = ""
    if isinstance(current_time, str) and len(current_time) >= 10:
        try:
            current_weekday = datetime.strptime(current_time[:10], "%Y-%m-%d").strftime("%A")
        except ValueError:
            current_weekday = ""

    st.subheader(f"Current weather — {city}")
    if current_weekday:
        st.markdown(
            f"<div class='wx-current-time'>{current_weekday} • {current_time}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='wx-current-time'>As of {current_time}</div>",
            unsafe_allow_html=True,
        )

    header_cols = st.columns([1, 3])
    with header_cols[0]:
        if icon_uri:
            st.image(f"{icon_uri}.png", width=96)
    with header_cols[1]:
        st.markdown(f"### {condition}")
        st.markdown(f"<div class='wx-current-temp'>{temp}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='wx-current-meta'>Feels like {feels}</div>",
            unsafe_allow_html=True,
        )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Humidity", f"{humidity}%" if humidity != "—" else "—")
    metric_cols[1].metric(
        "Wind",
        f"{wind_speed} {wind_unit}".strip() if wind_speed != "—" else "—",
        delta=wind_dir or None,
        delta_color="off",
    )
    metric_cols[2].metric("UV index", uv)
    metric_cols[3].metric("Precip.", f"{precip_pct}%" if precip_pct != "—" else "—")


def _render_forecast(forecast: Any, city: str) -> None:
    st.subheader(f"7-day forecast — {city}")
    if not isinstance(forecast, dict) or not forecast:
        st.error("Could not load forecast.")
        st.code(str(forecast))
        return

    rows = []
    for date_key, day in forecast.items():
        if not isinstance(day, dict):
            continue
        weekday = day.get("weekday") or _weekday_from_date_key(date_key)
        rows.append(
            {
                "Day": weekday,
                "Date": date_key,
                "High": _format_temp(day.get("maxTemp")),
                "Low": _format_temp(day.get("minTemp")),
                "Feels High": _format_temp(day.get("feelsLikeMaxTemp")),
                "Feels Low": _format_temp(day.get("feelsLikeMinTemp")),
                "Condition (Day)": day.get("daytimeWeatherCondition", "—"),
                "Day Precip %": day.get("daytimePrecipitationPercent", "—"),
                "Condition (Night)": day.get("nighttimeWeatherCondition", "—"),
                "Night Precip %": day.get("nighttimePrecipitationPercent", "—"),
                "UV (Day)": day.get("daytimeUvIndex", "—"),
            }
        )
    if not rows:
        st.info("No forecast data returned.")
        return

    # Visual day cards.
    card_cols = st.columns(min(len(rows), 7))
    for col, row in zip(card_cols, rows[:7]):
        with col:
            st.markdown(f"**{row['Day']}**")
            st.caption(row["Date"])
            st.markdown(f"☀️ {row['High']} / 🌙 {row['Low']}")
            st.caption(row["Condition (Day)"])
            st.caption(f"💧 {row['Day Precip %']}%")

    with st.expander("Detailed table", expanded=False):
        st.dataframe(rows, width='stretch', hide_index=True)


# --- Hourly forecast rendering ---
def _render_hourly(hourly: Any, city: str, hours: int, view_mode: str) -> None:
    st.subheader(f"Hourly forecast — {city}")
    if isinstance(hourly, dict) and "error" in hourly:
        st.error("Could not load hourly forecast.")
        st.code(str(hourly["error"]))
        return
    if not isinstance(hourly, list) or not hourly:
        st.info("No hourly forecast data returned.")
        return

    sliced = hourly[:hours]
    if not sliced:
        st.info("No hourly data returned.")
        return

    if view_mode == "Chart":
        chart_df = pd.DataFrame(
            [
                {
                    "Time": pd.to_datetime(hour.get("datetime"), errors="coerce"),
                    "Temperature": hour.get("temperature"),
                    "Feels Like": hour.get("feelsLike"),
                    "Precip %": hour.get("precipitationPercent") or 0,
                    "Condition": hour.get("weatherCondition") or "—",
                }
                for hour in sliced
            ]
        ).dropna(subset=["Time"])

        if chart_df.empty:
            st.info("No chartable hourly data.")
            return

        temp_long = chart_df.melt(
            id_vars=["Time", "Condition"],
            value_vars=["Temperature", "Feels Like"],
            var_name="Series",
            value_name="°F",
        ).dropna(subset=["°F"])

        base = alt.Chart(chart_df).encode(
            x=alt.X("Time:T", title="Time", axis=alt.Axis(format="%a %-I %p")),
        )
        precip_bars = base.mark_bar(opacity=0.25, color="#3b82f6").encode(
            y=alt.Y(
                "Precip %:Q",
                title="Precipitation %",
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(orient="right"),
            ),
            tooltip=[
                alt.Tooltip("Time:T", format="%a %-I %p"),
                alt.Tooltip("Precip %:Q", title="Precip %"),
                alt.Tooltip("Condition:N"),
            ],
        )
        temp_lines = (
            alt.Chart(temp_long)
            .mark_line(point=True, interpolate="monotone")
            .encode(
                x=alt.X("Time:T", title="Time", axis=alt.Axis(format="%a %-I %p")),
                y=alt.Y("°F:Q", title="Temperature (°F)"),
                color=alt.Color(
                    "Series:N",
                    legend=None,
                    scale=alt.Scale(
                        domain=["Temperature", "Feels Like"],
                        range=["#ef4444", "#f59e0b"],
                    ),
                ),
                tooltip=[
                    alt.Tooltip("Time:T", format="%a %-I %p"),
                    alt.Tooltip("Series:N"),
                    alt.Tooltip("°F:Q", format=".1f"),
                    alt.Tooltip("Condition:N"),
                ],
            )
        )
        layered = (
            alt.layer(precip_bars, temp_lines)
            .resolve_scale(y="independent")
            .properties(height=380)
        )
        st.altair_chart(layered, width='stretch')
        st.caption(
            "🔴 Temperature &nbsp;&nbsp; 🟡 Feels Like &nbsp;&nbsp;"
            " 🔵 Precipitation % (right axis, bars)"
        )

        # Compact summary stats below the chart
        temps = [h.get("temperature") for h in sliced if h.get("temperature") is not None]
        precip = [h.get("precipitationPercent") for h in sliced if h.get("precipitationPercent") is not None]
        if temps:
            stat_cols = st.columns(4)
            stat_cols[0].metric("High", f"{max(temps):.0f}°F")
            stat_cols[1].metric("Low", f"{min(temps):.0f}°F")
            stat_cols[2].metric("Avg", f"{sum(temps)/len(temps):.0f}°F")
            stat_cols[3].metric(
                "Max precip %",
                f"{max(precip):.0f}%" if precip else "—",
            )
        return

    # Table view
    rows = [
        {
            "Time": hour.get("datetime", "—"),
            "Temp": _format_temp(hour.get("temperature")),
            "Feels": _format_temp(hour.get("feelsLike")),
            "Condition": hour.get("weatherCondition", "—"),
            "Precip %": hour.get("precipitationPercent", "—"),
            "Precip Type": hour.get("precipitationType", "—"),
            "UV": hour.get("uvIndex", "—"),
            "Thunderstorm %": hour.get("thunderstormProbability", "—"),
        }
        for hour in sliced
    ]
    st.dataframe(rows, width='stretch', hide_index=True)


# ---------------------------------------------------------------------------
# Location selection
# ---------------------------------------------------------------------------

if "weather_city" not in st.session_state:
    st.session_state.weather_city = DEFAULT_WEATHER_LOCATION

with st.sidebar:
    st.subheader("Location")
    st.caption(f"Default location: **{DEFAULT_WEATHER_LOCATION}**")
    geo = render_browser_location_widget(key_prefix="weather_geo")
    # Auto-update city whenever new coordinates arrive (no extra button needed)
    if geo and geo != st.session_state.get("weather_geo_used"):
        resolved = _city_from_coords(geo["lat"], geo["lng"])
        st.session_state.weather_geo_used = geo
        if resolved:
            st.session_state.weather_city = resolved
            st.rerun()
        else:
            st.warning(
                "Couldn't reverse-geocode your coordinates. "
                f"Falling back to default ({DEFAULT_WEATHER_LOCATION})."
            )
            st.session_state.weather_city = DEFAULT_WEATHER_LOCATION

city_input = st.text_input(
    "Show weather for city",
    value=st.session_state.weather_city,
    placeholder=f"e.g. {DEFAULT_WEATHER_LOCATION}",
    help=(
        "Leave blank to use your browser location (if granted) or the "
        "configured DEFAULT_WEATHER_LOCATION."
    ),
)

refresh_cols = st.columns([1, 1, 6])
with refresh_cols[0]:
    refresh = st.button("🔄 Refresh", width='stretch')
with refresh_cols[1]:
    use_default = st.button("🏠 Default", width='stretch')

if use_default:
    st.session_state.weather_city = DEFAULT_WEATHER_LOCATION
    city_input = DEFAULT_WEATHER_LOCATION
elif city_input and city_input.strip() and city_input != st.session_state.weather_city:
    st.session_state.weather_city = city_input.strip()

# Effective city to query.
city = (st.session_state.weather_city or DEFAULT_WEATHER_LOCATION).strip()

# ---------------------------------------------------------------------------
# Data fetching (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_current(city_name: str) -> Any:
    return get_current_weather_tool.invoke({"city": city_name})

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_forecast(city_name: str, days: int) -> Any:
    return get_weather_forecast_tool.invoke({"city": city_name, "days": days})

@st.cache_data(ttl=600, show_spinner=False)
def _fetch_hourly(city_name: str, hours: int) -> Any:
    return get_hourly_weather_tool.invoke({"city": city_name, "hours": hours})

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_alerts(city_name: str) -> Any:
    return get_weather_alerts_tool.invoke({"city": city_name})

if refresh:
    _fetch_current.clear()
    _fetch_forecast.clear()
    _fetch_hourly.clear()
    _fetch_alerts.clear()

# --- Weather Alerts Display (uses the resolved city) ---
alerts = _fetch_alerts(city)
if isinstance(alerts, dict):
    if "error" in alerts:
        st.warning(f"Weather alert fetch error: {alerts['error']}")
    elif alerts.get("alerts"):
        for alert in alerts["alerts"]:
            title_obj = alert.get("alertTitle") or {}
            title = title_obj.get("text") if isinstance(title_obj, dict) else str(title_obj)
            title = title or alert.get("eventType", "Weather Alert")
            severity = alert.get("severity", "")
            area = alert.get("areaName", "")
            desc = alert.get("description", "")
            source = alert.get("dataSource") or {}
            source_name = source.get("name", "")
            source_uri = source.get("authorityUri", "")
            header = f"🚨 {title}"
            if severity:
                header += f" — {severity.capitalize()}"
            if area:
                header += f" ({area})"
            st.error(header)
            if desc:
                st.markdown(f"> {desc}")
            if source_name:
                attribution = f"Source: [{source_name}]({source_uri})" if source_uri else f"Source: {source_name}"
                st.caption(attribution)
    elif alerts.get("message"):
        st.info(alerts["message"])

# --- Current weather (above forecast tabs) ---
with st.spinner(f"Fetching weather for {city}…"):
    current = _fetch_current(city)

_render_current(current if isinstance(current, dict) else {}, city)
st.divider()

# --- Forecast tabs ---

tab1, tab2 = st.tabs(["7-day forecast", "Hourly forecast"])

with tab1:
    with st.spinner("Loading 7-day forecast..."):
        forecast = _fetch_forecast(city, 7)
        _render_forecast(forecast, city)

with tab2:
    hourly_controls = st.columns([2, 2, 6])
    with hourly_controls[0]:
        hourly_view = st.radio(
            "View",
            options=["Chart", "Table"],
            index=0,
            horizontal=True,
            key="hourly_view_mode",
        )
    with hourly_controls[1]:
        hourly_hours = st.selectbox(
            "Hours",
            options=[12, 24, 48, 72, 120, 240],
            index=1,
            key="hourly_hours_choice",
            help="How many hours of forecast to show (Google Weather API max 240).",
        )
    with st.spinner("Loading hourly forecast..."):
        hourly = _fetch_hourly(city, int(hourly_hours))
        _render_hourly(hourly, city, int(hourly_hours), hourly_view)
