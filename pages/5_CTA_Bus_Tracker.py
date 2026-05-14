"""Streamlit page for browsing CTA Bus Tracker predictions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:  # graceful fallback if not installed yet
    st_autorefresh = None  # type: ignore[assignment]

try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:  # graceful fallback if not installed yet
    streamlit_geolocation = None  # type: ignore[assignment]

from tools.cta_bus_tool import (
    DATA_DIR,
    cta_get_directions,
    cta_get_routes,
    cta_get_stops,
    cta_get_stop_catalog,
    get_all_nearby_bus_predictions_tool,
    get_bus_predictions_for_stop_tool,
    get_bus_predictions_near_location_tool,
)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="CTA Bus Tracker", page_icon="🚌", layout="wide")

FAVORITES_PATH = DATA_DIR / "cta_favorite_stops.json"


# ---------------------------------------------------------------------------
# Cached lookups
# ---------------------------------------------------------------------------


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_routes() -> list[dict[str, Any]]:
    return cta_get_routes()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_directions(route: str) -> list[dict[str, Any]]:
    return cta_get_directions(route)


@st.cache_data(ttl=60 * 60, show_spinner=False)
def load_stops(route: str, direction: str) -> list[dict[str, Any]]:
    return cta_get_stops(route=route, direction=direction)


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


def add_favorite(label: str, stop_id: str, route: str | None = None) -> None:
    favs = load_favorites()
    if any(f["stop_id"] == stop_id and (f.get("route") or None) == (route or None) for f in favs):
        return
    favs.append({"label": label, "stop_id": stop_id, "route": route})
    save_favorites(favs)


def remove_favorite(stop_id: str, route: str | None) -> None:
    favs = [
        f for f in load_favorites()
        if not (f["stop_id"] == stop_id and (f.get("route") or None) == (route or None))
    ]
    save_favorites(favs)


def _save_favorite_callback(slot: str, label: str, stop_id: str, route: str | None) -> None:
    """Streamlit button on_click handler — runs before the next render."""
    add_favorite(label=label, stop_id=stop_id, route=route)
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
        "route_direction",
        "destination",
        "minutes_until",
        "predicted_time",
        "type",
        "delayed",
        "stop_name",
        "stop_id",
        "distance_miles",
        "vehicle_id",
        "passenger_load",
        "dynamic_action",
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
        st.warning(result.get("message", "Multiple stops matched."))
        st.dataframe(pd.DataFrame(result.get("candidates", [])), use_container_width=True)
        return
    if "message" in result and not result.get("predictions"):
        st.info(result["message"])
        return

    meta_cols = st.columns(3)
    if "stop_name" in result:
        meta_cols[0].metric("Stop", result.get("stop_name") or "—")
        meta_cols[1].metric("Stop ID", result.get("stop_id") or "—")
        meta_cols[2].metric("Predictions", result.get("prediction_count", 0))
    elif "location" in result:
        loc = result["location"]
        meta_cols[0].metric("Lat, Lng", f"{loc['lat']:.5f}, {loc['lng']:.5f}")
        meta_cols[1].metric("Stops in radius", result.get("stops_found", 0))
        meta_cols[2].metric(
            "Routes" if "routes_found" in result else "Predictions",
            result.get("routes_found", result.get("prediction_count", 0)),
        )

    if result.get("routes"):
        st.markdown("**Routes near this location**")
        st.dataframe(
            pd.DataFrame(result["routes"]),
            use_container_width=True,
            hide_index=True,
        )

    df = _predictions_dataframe(result.get("predictions", []))
    if df.empty:
        st.info("No upcoming predictions.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    if "stops" in result and result["stops"]:
        with st.expander("Stops within radius"):
            st.dataframe(pd.DataFrame(result["stops"]), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------


st.title("🚌 CTA Bus Tracker")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

# --- Auto refresh control --------------------------------------------------
with st.sidebar:
    refresh_choice = st.radio(
        "Auto-refresh",
        options=["Off", "30 seconds", "60 seconds"],
        index=0,
        help="CTA updates predictions about every 30 seconds.",
    )
    refresh_ms = {"Off": 0, "30 seconds": 30_000, "60 seconds": 60_000}[refresh_choice]
    if refresh_ms and st_autorefresh is not None:
        st_autorefresh(interval=refresh_ms, key="cta_autorefresh")
    elif refresh_ms and st_autorefresh is None:
        st.warning("Install `streamlit-autorefresh` to enable auto refresh.")

    st.markdown("---")
    bus_counter_path = DATA_DIR / "cta_call_count.json"
    if bus_counter_path.exists():
        try:
            counter = json.loads(bus_counter_path.read_text(encoding="utf-8"))
            st.metric(
                f"Bus API calls today ({counter.get('date', '?')})",
                f"{counter.get('count', 0):,} / 100,000",
            )
        except json.JSONDecodeError:
            pass
    if st.button("Rebuild stop catalog"):
        with st.spinner("Rebuilding CTA bus stop catalog (~390 calls)…"):
            cta_get_stop_catalog(force_refresh=True)
        st.success("Bus stop catalog rebuilt.")

tab_favs, tab_stop, tab_nearby, tab_browse = st.tabs(
    ["Favorites", "By Stop", "Near Location", "Browse Route"]
)

# --- Tab 1: By stop --------------------------------------------------------
with tab_stop:
    st.subheader("Predictions for a specific stop")
    mode = st.radio(
        "Identify the stop by",
        options=["Stop ID", "Route + Direction + Stop name"],
        horizontal=True,
        key="stop_lookup_mode",
    )

    if mode == "Stop ID":
        with st.form("by_stop_id_form"):
            stop_id = st.text_input("CTA Stop ID (stpid)", placeholder="e.g. 456")
            route_filter = st.text_input(
                "Route filter (optional)", placeholder="e.g. 20"
            ).strip() or None
            submitted = st.form_submit_button("Get predictions")
        if submitted and stop_id.strip():
            st.session_state["byid_query"] = {
                "payload": {"stop_id": stop_id.strip(), "route": route_filter},
                "stop": stop_id.strip(),
                "route_filter": route_filter,
            }
            st.session_state.pop("byid_saved_msg", None)

        query = st.session_state.get("byid_query")
        if query is not None:
            with st.spinner("Calling CTA Bus Tracker…"):
                result = get_bus_predictions_for_stop_tool.invoke(query["payload"])
            _render_result(result)
            if isinstance(result, dict) and result.get("stop_id") and not result.get("error"):
                rid = str(result["stop_id"])
                rname = result.get("stop_name") or query.get("stop") or rid
                st.button(
                    "⭐ Save as favorite",
                    key="fav_save_byid",
                    on_click=_save_favorite_callback,
                    args=(
                        "byid",
                        f"{rname} ({rid})",
                        rid,
                        query.get("route_filter"),
                    ),
                )
            saved_msg = st.session_state.get("byid_saved_msg")
            if saved_msg:
                st.success(saved_msg)

    else:
        with st.form("by_route_dir_name_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                route = st.text_input("Route", placeholder="e.g. 20").strip()
            with c2:
                direction = st.selectbox(
                    "Direction",
                    options=["Eastbound", "Westbound", "Northbound", "Southbound"],
                    index=0,
                    help=(
                        "CTA route directions. Not every route serves every "
                        "direction \u2014 if the lookup returns no stops, try "
                        "the perpendicular pair."
                    ),
                )
            with c3:
                stop_name = st.text_input(
                    "Stop name (substring)", placeholder="e.g. Madison & State"
                ).strip()
            submitted = st.form_submit_button("Get predictions")
        if submitted:
            if not (route and direction and stop_name):
                st.error("Route, direction, and stop name are all required.")
            else:
                st.session_state["byrdn_query"] = {
                    "route": route,
                    "direction": direction,
                    "stop_name": stop_name,
                }

        byrdn_query = st.session_state.get("byrdn_query")
        if byrdn_query is not None:
            with st.spinner("Calling CTA Bus Tracker…"):
                result = get_bus_predictions_for_stop_tool.invoke(byrdn_query)
            _render_result(result)

# --- Tab 2: Near location --------------------------------------------------
with tab_nearby:
    st.subheader("Predictions for stops near a location")
    st.caption(
        "The CTA API has no native 'stops near coordinates' endpoint. "
        "Leave **Route** blank to search ALL CTA routes (uses a 24h on-disk "
        "stop catalog \u2014 the first build of the day takes ~30\u201360s). "
        "Provide a route to limit the search to that route only."
    )

    # Location-mode selector + browser-geolocation widget live OUTSIDE the
    # form so they can rerun on click. The form below only consumes the
    # selected mode + cached browser coords from session_state.
    loc_options = ["Lat / Lng", "Address", "Use my browser location"]
    loc_mode = st.radio(
        "Location input",
        loc_options,
        horizontal=True,
        key="nearby_loc_mode",
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

    with st.form("nearby_form"):
        c1, c2 = st.columns(2)
        with c1:
            route = st.text_input(
                "Route (blank = all routes)", placeholder="e.g. 20 — leave blank for all"
            ).strip()
            radius = st.number_input(
                "Radius (miles)", min_value=0.05, max_value=5.0, value=0.25, step=0.05
            )
            direction_choice = st.selectbox(
                "Direction (ignored when Route is blank)",
                options=[
                    "Any (both directions)",
                    "Eastbound",
                    "Westbound",
                    "Northbound",
                    "Southbound",
                ],
                index=0,
            )
            direction = (
                None if direction_choice == "Any (both directions)"
                else direction_choice
            )
        with c2:
            lat: float | None = None
            lng: float | None = None
            address: str | None = None
            if loc_mode == "Lat / Lng":
                lat = st.number_input("Latitude", value=41.8781, format="%.6f")
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
                    st.write(
                        f"**Browser location:** {lat:.5f}, {lng:.5f}"
                    )
                else:
                    st.info(
                        "Capture your browser location above before submitting."
                    )
        submitted = st.form_submit_button("Get predictions")
    if submitted:
        if loc_mode == "Address" and not address:
            st.error("Address is required.")
        elif loc_mode == "Use my browser location" and (lat is None or lng is None):
            st.error(
                "Browser location not available. Click the location button "
                "above and approve the permission prompt before submitting."
            )
        else:
            if route:
                payload: dict[str, Any] = {
                    "route": route,
                    "radius_miles": float(radius),
                    "direction": direction,
                }
                if address:
                    payload["address"] = address
                else:
                    payload["lat"] = float(lat)  # type: ignore[arg-type]
                    payload["lng"] = float(lng)  # type: ignore[arg-type]
                st.session_state["nearby_query"] = {
                    "tool": "route",
                    "payload": payload,
                }
            else:
                payload = {"radius_miles": float(radius)}
                if address:
                    payload["address"] = address
                else:
                    payload["lat"] = float(lat)  # type: ignore[arg-type]
                    payload["lng"] = float(lng)  # type: ignore[arg-type]
                st.session_state["nearby_query"] = {
                    "tool": "all",
                    "payload": payload,
                }

    nearby_query = st.session_state.get("nearby_query")
    if nearby_query is not None:
        if nearby_query["tool"] == "route":
            with st.spinner("Calling CTA Bus Tracker…"):
                result = get_bus_predictions_near_location_tool.invoke(
                    nearby_query["payload"]
                )
        else:
            with st.spinner(
                "Searching all CTA routes near your location… "
                "(first call of the day may take ~30\u201360s)"
            ):
                result = get_all_nearby_bus_predictions_tool.invoke(
                    nearby_query["payload"]
                )
        _render_result(result)

# --- Tab 3: Browse route to discover stops --------------------------------
with tab_browse:
    st.subheader("Browse stops on a route")
    routes = []
    try:
        routes = load_routes()
    except Exception as exc:
        st.error(f"Could not load CTA route list: {exc}")
    if routes:
        labels = [f"{r.get('rt')} — {r.get('rtnm')}" for r in routes]
        sel = st.selectbox("Route", options=range(len(routes)), format_func=lambda i: labels[i])
        chosen_route = routes[sel].get("rt")
        try:
            dirs = load_directions(chosen_route)
        except Exception as exc:
            dirs = []
            st.error(f"Could not load directions: {exc}")
        if dirs:
            dir_id = st.selectbox(
                "Direction",
                options=[d.get("id") for d in dirs],
                format_func=lambda x: x or "(unknown)",
            )
            if dir_id:
                try:
                    stops = load_stops(chosen_route, dir_id)
                except Exception as exc:
                    stops = []
                    st.error(f"Could not load stops: {exc}")
                if stops:
                    stops_df = pd.DataFrame(
                        [
                            {
                                "Stop ID": s.get("stpid"),
                                "Stop Name": s.get("stpnm"),
                                "Lat": s.get("lat"),
                                "Lon": s.get("lon"),
                            }
                            for s in stops
                        ]
                    )
                    st.dataframe(stops_df, use_container_width=True, hide_index=True)
                    pick = st.selectbox(
                        "Pick a stop to view predictions",
                        options=stops_df["Stop ID"].astype(str).tolist(),
                        format_func=lambda sid: f"{sid} — "
                        + stops_df.set_index(stops_df['Stop ID'].astype(str)).loc[sid, 'Stop Name'],
                    )
                    if st.button("Get predictions for selected stop"):
                        st.session_state["browse_query"] = {
                            "payload": {"stop_id": str(pick), "route": chosen_route},
                            "pick": str(pick),
                            "route": chosen_route,
                        }
                        st.session_state.pop("browse_saved_msg", None)

                    browse_query = st.session_state.get("browse_query")
                    if browse_query is not None:
                        with st.spinner("Calling CTA Bus Tracker…"):
                            result = get_bus_predictions_for_stop_tool.invoke(
                                browse_query["payload"]
                            )
                        _render_result(result)
                        if isinstance(result, dict) and not result.get("error"):
                            rid = browse_query.get("pick", str(pick))
                            rname = result.get("stop_name") or rid
                            st.button(
                                "⭐ Save as favorite",
                                key="fav_save_browse",
                                on_click=_save_favorite_callback,
                                args=(
                                    "browse",
                                    f"{rname} ({rid})",
                                    str(rid),
                                    browse_query.get("route"),
                                ),
                            )
                        saved_msg = st.session_state.get("browse_saved_msg")
                        if saved_msg:
                            st.success(saved_msg)

# --- Tab 4: Favorites ------------------------------------------------------
with tab_favs:
    st.subheader("Favorite stops")
    favs = load_favorites()
    if not favs:
        st.info("No favorites yet. Save a stop from the other tabs.")
    else:
        for idx, fav in enumerate(favs):
            with st.container(border=True):
                cols = st.columns([4, 1, 1])
                cols[0].markdown(
                    f"**{fav['label']}**  \nStop ID: `{fav['stop_id']}`"
                    + (f" · Route: `{fav['route']}`" if fav.get("route") else "")
                )
                fav_token = f"{fav['stop_id']}|{fav.get('route') or ''}"
                active_key = f"fav_active::{fav_token}"
                if cols[1].button("Refresh", key=f"fav_get_{idx}"):
                    st.session_state[active_key] = True
                if st.session_state.get(active_key):
                    with st.spinner("Calling CTA Bus Tracker…"):
                        result = get_bus_predictions_for_stop_tool.invoke(
                            {"stop_id": fav["stop_id"], "route": fav.get("route")}
                        )
                    _render_result(result)
                pending_key = "fav_pending_remove"
                if st.session_state.get(pending_key) == fav_token:
                    cols[2].button(
                        "Remove",
                        key=f"fav_del_{idx}",
                        disabled=True,
                    )
                    st.warning(
                        f"Remove **{fav['label']}** from favorites?"
                    )
                    confirm_cols = st.columns(2)
                    if confirm_cols[0].button(
                        "Yes, remove", key=f"fav_del_confirm_{idx}", type="primary"
                    ):
                        remove_favorite(fav["stop_id"], fav.get("route"))
                        st.session_state.pop(pending_key, None)
                        st.session_state.pop(active_key, None)
                        st.rerun()
                    if confirm_cols[1].button("Cancel", key=f"fav_del_cancel_{idx}"):
                        st.session_state.pop(pending_key, None)
                        st.rerun()
                else:
                    if cols[2].button("Remove", key=f"fav_del_{idx}"):
                        st.session_state[pending_key] = fav_token
                        st.rerun()
