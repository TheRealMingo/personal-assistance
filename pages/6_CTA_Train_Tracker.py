"""Streamlit page for browsing CTA Train Tracker arrivals."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None  # type: ignore[assignment]

try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:
    streamlit_geolocation = None  # type: ignore[assignment]

from tools.cta_train_tool import (
    DATA_DIR,
    ROUTE_COLUMN_TO_CTA,
    cta_get_train_station_catalog,
    get_all_nearby_train_arrivals_tool,
    get_train_arrivals_for_station_tool,
)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="CTA Train Tracker", page_icon="🚆", layout="wide")

FAVORITES_PATH = DATA_DIR / "cta_favorite_stations.json"

# Map of CTA rt code -> friendly name (built from ROUTE_COLUMN_TO_CTA).
ROUTE_RT_TO_NAME: dict[str, str] = {
    info["rt"]: info["name"] for info in ROUTE_COLUMN_TO_CTA.values()
}

# Official CTA brand colors keyed by the rt code returned by Train Tracker.
LINE_COLORS: dict[str, str] = {
    "Red":  "#C60C30",
    "Blue": "#00A1DE",
    "Brn":  "#62361B",
    "G":    "#009B3A",
    "Org":  "#F9461C",
    "Pink": "#E27EA6",
    "P":    "#522398",
    "Pexp": "#522398",
    "Y":    "#F9E300",
}

# Lines whose brand color is too light for white text (e.g. yellow, pink).
_DARK_TEXT_LINES = {"Y", "Pink"}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _tint_css(rt: str | None, alpha: float = 0.22) -> str:
    """Return a CSS ``background-color: ...`` string tinted by line color.

    Uses an rgba fill so the row reads as a soft wash that still works on
    Streamlit's light/dark themes. Returns an empty string when the line is
    unknown.
    """
    if not rt:
        return ""
    hex_color = LINE_COLORS.get(rt)
    if not hex_color:
        return ""
    r, g, b = _hex_to_rgb(hex_color)
    return f"background-color: rgba({r}, {g}, {b}, {alpha})"


def _style_rows_by_line(
    df: pd.DataFrame,
    *,
    line_col: str | None = None,
    fixed_line: str | None = None,
    routes_col: str | None = None,
) -> Any:
    """Return a pandas Styler that tints each row by its CTA line color.

    Exactly one of these should drive the color choice per row:
      - ``line_col``: name of a single-string column holding the rt code.
      - ``routes_col``: name of a list-valued column; uses the first entry.
      - ``fixed_line``: a single rt code applied to every row.
    """
    def _row_style(row: pd.Series) -> list[str]:
        if fixed_line is not None:
            rt = fixed_line
        elif line_col and line_col in row.index:
            rt = row[line_col]
        elif routes_col and routes_col in row.index:
            val = row[routes_col]
            rt = val[0] if isinstance(val, (list, tuple)) and val else None
        else:
            rt = None
        css = _tint_css(rt if isinstance(rt, str) else None)
        return [css] * len(row)
    return df.style.apply(_row_style, axis=1)


# ---------------------------------------------------------------------------
# Cached lookups
# ---------------------------------------------------------------------------


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_station_catalog() -> dict[str, Any]:
    return cta_get_train_station_catalog()


# ---------------------------------------------------------------------------
# Favorites persistence
# ---------------------------------------------------------------------------


def load_favorites() -> list[dict[str, Any]]:
    if not FAVORITES_PATH.exists():
        return []
    try:
        return json.loads(FAVORITES_PATH.read_text(encoding="utf-8")) or []
    except json.JSONDecodeError:
        return []


def save_favorites(favs: list[dict[str, Any]]) -> None:
    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_PATH.write_text(json.dumps(favs, indent=2), encoding="utf-8")


def add_favorite(label: str, station_id: str, route: str | None = None) -> None:
    favs = load_favorites()
    if any(
        f["station_id"] == station_id and (f.get("route") or None) == (route or None)
        for f in favs
    ):
        return
    favs.append({"label": label, "station_id": station_id, "route": route})
    save_favorites(favs)


def remove_favorite(station_id: str, route: str | None) -> None:
    favs = [
        f for f in load_favorites()
        if not (
            f["station_id"] == station_id
            and (f.get("route") or None) == (route or None)
        )
    ]
    save_favorites(favs)


def _save_favorite_callback(
    slot: str, label: str, station_id: str, route: str | None
) -> None:
    add_favorite(label=label, station_id=station_id, route=route)
    st.session_state[f"{slot}_saved_msg"] = f"Saved “{label}” to favorites."


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _predictions_dataframe(predictions: list[dict[str, Any]]) -> pd.DataFrame:
    if not predictions:
        return pd.DataFrame()
    df = pd.DataFrame(predictions)
    preferred_cols = [
        "route",
        "destination",
        "minutes_until",
        "arrival_time",
        "platform",
        "station_name",
        "station_id",
        "distance_miles",
        "approaching",
        "scheduled",
        "delayed",
        "fault",
        "run_number",
    ]
    cols = [c for c in preferred_cols if c in df.columns]
    return df[cols]


def _render_result(result: Any) -> None:
    if isinstance(result, str):
        st.error(result)
        return
    if not isinstance(result, dict):
        st.write(result)
        return
    if "error" in result:
        st.error(result["error"])
        return
    if result.get("ambiguous"):
        st.warning(result.get("message", "Multiple stations matched."))
        st.dataframe(
            pd.DataFrame(result.get("candidates", [])),
            use_container_width=True,
            hide_index=True,
        )
        return
    if "message" in result and not result.get("predictions"):
        st.info(result["message"])
        return

    meta_cols = st.columns(3)
    if "station_name" in result and "stations_found" not in result:
        meta_cols[0].metric("Station", result.get("station_name") or "—")
        meta_cols[1].metric("Station ID", result.get("station_id") or "—")
        meta_cols[2].metric("Predictions", result.get("prediction_count", 0))
    elif "location" in result:
        loc = result["location"]
        meta_cols[0].metric("Lat, Lng", f"{loc['lat']:.5f}, {loc['lng']:.5f}")
        meta_cols[1].metric("Stations in radius", result.get("stations_found", 0))
        meta_cols[2].metric("Lines", result.get("routes_found", 0))

    if result.get("routes"):
        st.markdown("**Lines near this location**")
        routes_df = pd.DataFrame(result["routes"])
        if "route" in routes_df.columns:
            routes_df["line"] = routes_df["route"].map(
                lambda r: ROUTE_RT_TO_NAME.get(r, r)
            )
            cols_order = [
                "route",
                "line",
                "nearest_station_name",
                "nearest_station_id",
                "nearest_distance_miles",
            ]
            routes_df = routes_df[[c for c in cols_order if c in routes_df.columns]]
            st.dataframe(
                _style_rows_by_line(routes_df, line_col="route"),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.dataframe(routes_df, use_container_width=True, hide_index=True)

    df = _predictions_dataframe(result.get("predictions", []))
    if df.empty:
        st.info("No upcoming train arrivals.")
    else:
        st.dataframe(
            _style_rows_by_line(df, line_col="route"),
            use_container_width=True,
            hide_index=True,
        )

    if result.get("stations"):
        with st.expander("Stations within radius"):
            stations_df = pd.DataFrame(result["stations"])
            if "routes" in stations_df.columns:
                st.dataframe(
                    _style_rows_by_line(stations_df, routes_col="routes"),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.dataframe(
                    stations_df,
                    use_container_width=True,
                    hide_index=True,
                )

    if result.get("response_generated_at"):
        st.caption(f"CTA response generated at: {result['response_generated_at']}")


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------


st.title("🚆 CTA Train Tracker")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

# --- Quota / catalog status sidebar ----------------------------------------
with st.sidebar:
    refresh_choice = st.radio(
        "Auto-refresh",
        options=["Off", "30 seconds", "60 seconds"],
        index=0,
        help="CTA train arrivals update roughly every 30 seconds.",
    )
    refresh_ms = {"Off": 0, "30 seconds": 30_000, "60 seconds": 60_000}[refresh_choice]
    if refresh_ms and st_autorefresh is not None:
        st_autorefresh(interval=refresh_ms, key="cta_train_autorefresh")
    elif refresh_ms and st_autorefresh is None:
        st.warning("Install `streamlit-autorefresh` to enable auto refresh.")

    st.markdown("---")
    counter_path = DATA_DIR / "cta_train_call_count.json"
    if counter_path.exists():
        try:
            counter = json.loads(counter_path.read_text(encoding="utf-8"))
            st.metric(
                f"Train API calls today ({counter.get('date', '?')})",
                f"{counter.get('count', 0):,} / 50,000",
            )
        except json.JSONDecodeError:
            pass
    if st.button("Rebuild station catalog"):
        cta_get_train_station_catalog(force_refresh=True)
        load_station_catalog.clear()
        st.success("Station catalog rebuilt from Chicago Data Portal.")

# --- Load catalog (used by multiple tabs) ----------------------------------
try:
    catalog = load_station_catalog()
    stations: list[dict[str, Any]] = catalog["stations"]
except Exception as exc:
    st.error(f"Could not load CTA train station catalog: {exc}")
    stations = []

stations_sorted = sorted(stations, key=lambda s: (s["station_name"] or "").lower())

tab_favs, tab_station, tab_nearby, tab_browse = st.tabs(
    ["Favorites", "By Station", "Near Location", "Browse Line"]
)


# --- Tab 1: By station -----------------------------------------------------
with tab_station:
    st.subheader("Arrivals at a specific station")
    mode = st.radio(
        "Identify the station by",
        options=["Pick from list", "Station ID (mapid)"],
        horizontal=True,
        key="train_station_mode",
    )

    with st.form("by_station_form"):
        chosen_mapid: str | None = None
        chosen_name: str | None = None
        if mode == "Pick from list" and stations_sorted:
            labels = [
                f"{s['station_name']} ({s['station_id']}) — "
                f"{', '.join(ROUTE_RT_TO_NAME.get(r, r) for r in s['routes'])}"
                for s in stations_sorted
            ]
            sel = st.selectbox(
                "Station",
                options=range(len(stations_sorted)),
                format_func=lambda i: labels[i],
            )
            chosen_mapid = stations_sorted[sel]["station_id"]
            chosen_name = stations_sorted[sel]["station_name"]
        else:
            chosen_mapid = st.text_input(
                "Station ID (mapid)", placeholder="e.g. 40380"
            ).strip() or None

        c1, c2 = st.columns(2)
        with c1:
            route_filter = st.selectbox(
                "Line filter (optional)",
                options=[None] + list(ROUTE_RT_TO_NAME.keys()),
                format_func=lambda r: "All lines" if r is None
                else f"{ROUTE_RT_TO_NAME[r]} ({r})",
            )
        with c2:
            max_results = st.number_input(
                "Max results (0 = all)", min_value=0, max_value=50,
                value=0, step=1,
            )
        submitted = st.form_submit_button("Get arrivals")

    if submitted:
        if not chosen_mapid:
            st.error("Please pick a station or enter a station ID.")
        else:
            payload: dict[str, Any] = {"station_id": chosen_mapid}
            if route_filter:
                payload["route"] = route_filter
            if max_results:
                payload["max_results"] = int(max_results)
            st.session_state["station_query"] = {
                "payload": payload,
                "name": chosen_name,
                "route": route_filter,
            }
            st.session_state.pop("station_saved_msg", None)

    station_query = st.session_state.get("station_query")
    if station_query is not None:
        with st.spinner("Calling CTA Train Tracker…"):
            result = get_train_arrivals_for_station_tool.invoke(station_query["payload"])
        _render_result(result)
        if isinstance(result, dict) and result.get("station_id") and not result.get("error"):
            sid = str(result["station_id"])
            sname = (
                result.get("station_name")
                or station_query.get("name")
                or sid
            )
            st.button(
                "⭐ Save as favorite",
                key="fav_save_station",
                on_click=_save_favorite_callback,
                args=(
                    "station",
                    f"{sname} ({sid})",
                    sid,
                    station_query.get("route"),
                ),
            )
        saved_msg = st.session_state.get("station_saved_msg")
        if saved_msg:
            st.success(saved_msg)


# --- Tab 2: Near location --------------------------------------------------
with tab_nearby:
    st.subheader("Arrivals at stations near a location")
    st.caption(
        "The Train Tracker API has no native 'stations near coordinates' "
        "endpoint. We use a 30-day cached station catalog from the Chicago "
        "Data Portal to find nearby stations, then fetch live arrivals "
        "(one API call per nearby station)."
    )

    loc_options = ["Lat / Lng", "Address", "Use my browser location"]
    loc_mode = st.radio(
        "Location input",
        loc_options,
        horizontal=True,
        key="train_nearby_loc_mode",
    )

    if loc_mode == "Use my browser location":
        if streamlit_geolocation is None:
            st.warning("Install `streamlit-geolocation` to use browser location.")
        else:
            st.caption(
                "Click the location button below and approve the browser "
                "permission prompt. The coordinates will be cached for this "
                "session."
            )
            geo = streamlit_geolocation()
            if (
                isinstance(geo, dict)
                and geo.get("latitude") is not None
                and geo.get("longitude") is not None
            ):
                st.session_state["browser_geo"] = {
                    "lat": float(geo["latitude"]),
                    "lng": float(geo["longitude"]),
                    "accuracy": geo.get("accuracy"),
                }
            cached = st.session_state.get("browser_geo")
            if cached:
                acc = cached.get("accuracy")
                acc_txt = f" (±{acc:.0f} m)" if isinstance(acc, (int, float)) else ""
                st.success(
                    f"Using browser location: {cached['lat']:.5f}, "
                    f"{cached['lng']:.5f}{acc_txt}"
                )
            else:
                st.info("No browser location captured yet.")

    with st.form("train_nearby_form"):
        radius = st.number_input(
            "Radius (miles)",
            min_value=0.1, max_value=5.0, value=0.5, step=0.1,
        )
        lat: float | None = None
        lng: float | None = None
        address: str | None = None
        if loc_mode == "Lat / Lng":
            c1, c2 = st.columns(2)
            with c1:
                lat = st.number_input("Latitude", value=41.8781, format="%.6f")
            with c2:
                lng = st.number_input("Longitude", value=-87.6298, format="%.6f")
        elif loc_mode == "Address":
            address = st.text_input(
                "Address", placeholder="e.g. 200 E Randolph St, Chicago, IL"
            ).strip() or None
        else:
            cached = st.session_state.get("browser_geo")
            if cached:
                lat = float(cached["lat"])
                lng = float(cached["lng"])
                st.write(f"**Browser location:** {lat:.5f}, {lng:.5f}")
            else:
                st.info("Capture your browser location above before submitting.")
        submitted = st.form_submit_button("Get arrivals")

    if submitted:
        if loc_mode == "Address" and not address:
            st.error("Address is required.")
        elif loc_mode == "Use my browser location" and (lat is None or lng is None):
            st.error(
                "Browser location not available. Click the location button "
                "above and approve the permission prompt before submitting."
            )
        else:
            payload = {"radius_miles": float(radius)}
            if address:
                payload["address"] = address
            else:
                payload["lat"] = float(lat)  # type: ignore[arg-type]
                payload["lng"] = float(lng)  # type: ignore[arg-type]
            st.session_state["train_nearby_query"] = payload

    train_nearby_query = st.session_state.get("train_nearby_query")
    if train_nearby_query is not None:
        with st.spinner("Calling CTA Train Tracker for each nearby station…"):
            result = get_all_nearby_train_arrivals_tool.invoke(train_nearby_query)
        _render_result(result)


# --- Tab 3: Browse a line --------------------------------------------------
with tab_browse:
    st.subheader("Browse stations on a line")
    if not stations:
        st.info("Station catalog not loaded.")
    else:
        line_rt = st.selectbox(
            "Line",
            options=list(ROUTE_RT_TO_NAME.keys()),
            format_func=lambda r: f"{ROUTE_RT_TO_NAME[r]} ({r})",
        )
        line_stations = [s for s in stations_sorted if line_rt in s["routes"]]
        if not line_stations:
            st.info("No stations found for that line.")
        else:
            stations_df = pd.DataFrame(
                [
                    {
                        "Station ID": s["station_id"],
                        "Station Name": s["station_name"],
                        "Descriptive Name": s["station_descriptive_name"],
                        "ADA": s["ada"],
                        "Lat": s["lat"],
                        "Lon": s["lon"],
                    }
                    for s in line_stations
                ]
            )
            st.dataframe(
                _style_rows_by_line(stations_df, fixed_line=line_rt),
                use_container_width=True,
                hide_index=True,
            )
            pick_label = st.selectbox(
                "Pick a station to view arrivals",
                options=[
                    f"{s['station_name']} ({s['station_id']})" for s in line_stations
                ],
            )
            picked = next(
                (
                    s for s in line_stations
                    if f"{s['station_name']} ({s['station_id']})" == pick_label
                ),
                None,
            )
            if picked and st.button("Get arrivals for selected station"):
                st.session_state["browse_train_query"] = {
                    "payload": {
                        "station_id": picked["station_id"],
                        "route": line_rt,
                    },
                    "pick": picked["station_id"],
                    "name": picked["station_name"],
                    "route": line_rt,
                }
                st.session_state.pop("browse_train_saved_msg", None)

            browse_train_query = st.session_state.get("browse_train_query")
            if browse_train_query is not None:
                with st.spinner("Calling CTA Train Tracker…"):
                    br_result = get_train_arrivals_for_station_tool.invoke(
                        browse_train_query["payload"]
                    )
                _render_result(br_result)
                if isinstance(br_result, dict) and not br_result.get("error"):
                    sid = browse_train_query.get("pick", "")
                    sname = (
                        br_result.get("station_name")
                        or browse_train_query.get("name")
                        or sid
                    )
                    st.button(
                        "⭐ Save as favorite",
                        key="fav_save_browse_train",
                        on_click=_save_favorite_callback,
                        args=(
                            "browse_train",
                            f"{sname} ({sid})",
                            str(sid),
                            browse_train_query.get("route"),
                        ),
                    )
                saved_msg = st.session_state.get("browse_train_saved_msg")
                if saved_msg:
                    st.success(saved_msg)


# --- Tab 4: Favorites ------------------------------------------------------
with tab_favs:
    st.subheader("Favorite stations")
    favs = load_favorites()
    if not favs:
        st.info("No favorites yet. Save a station from the other tabs.")
    else:
        for idx, fav in enumerate(favs):
            with st.container(border=True):
                cols = st.columns([4, 1, 1])
                cols[0].markdown(
                    f"**{fav['label']}**  \nStation ID: `{fav['station_id']}`"
                    + (
                        f" · Line: `{ROUTE_RT_TO_NAME.get(fav['route'], fav['route'])}`"
                        if fav.get("route") else ""
                    )
                )
                fav_token = f"{fav['station_id']}|{fav.get('route') or ''}"
                active_key = f"fav_train_active::{fav_token}"
                if cols[1].button("Refresh", key=f"fav_train_get_{idx}"):
                    st.session_state[active_key] = True
                if st.session_state.get(active_key):
                    payload: dict[str, Any] = {"station_id": fav["station_id"]}
                    if fav.get("route"):
                        payload["route"] = fav["route"]
                    with st.spinner("Calling CTA Train Tracker…"):
                        result = get_train_arrivals_for_station_tool.invoke(payload)
                    _render_result(result)
                pending_key = "fav_train_pending_remove"
                if st.session_state.get(pending_key) == fav_token:
                    cols[2].button(
                        "Remove",
                        key=f"fav_train_del_{idx}",
                        disabled=True,
                    )
                    st.warning(
                        f"Remove **{fav['label']}** from favorites?"
                    )
                    confirm_cols = st.columns(2)
                    if confirm_cols[0].button(
                        "Yes, remove",
                        key=f"fav_train_del_confirm_{idx}",
                        type="primary",
                    ):
                        remove_favorite(fav["station_id"], fav.get("route"))
                        st.session_state.pop(pending_key, None)
                        st.session_state.pop(active_key, None)
                        st.rerun()
                    if confirm_cols[1].button(
                        "Cancel", key=f"fav_train_del_cancel_{idx}"
                    ):
                        st.session_state.pop(pending_key, None)
                        st.rerun()
                else:
                    if cols[2].button("Remove", key=f"fav_train_del_{idx}"):
                        st.session_state[pending_key] = fav_token
                        st.rerun()
