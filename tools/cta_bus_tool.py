"""CTA Bus Tracker API tools.

Exposes three LangChain `@tool` functions plus internal helpers for the CTA
Bus Tracker v3 REST API:

    - get_bus_predictions_for_stop_tool: predictions for a single stop, by
      stpid OR by (route + direction + stop_name).
    - get_bus_predictions_near_location_tool: predictions for all stops on a
      given route within a radius of a lat/lng or street address.
    - get_all_nearby_bus_predictions_tool: predictions for ALL routes whose
      stops fall within a radius of a lat/lng or address. Uses an on-disk
      24h stop catalog so the slow fan-out only happens once per day.

Reference: cta_Bus_Tracker_API_Developer_Guide_and_Documentation_2025-04-21.md
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone as _timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import googlemaps
import requests
from langchain.tools import tool

from config.config import config
from tools.api_call_tracker import record_api_call as _record_central_api_call

logging.basicConfig(
    filename="personal_assistant_tool.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

CTA_BASE_URL = "https://www.ctabustracker.com/bustime/api/v3"
DEFAULT_RADIUS_MILES = 0.25
EARTH_RADIUS_MILES = 3958.7613

# --- Quota / caching configuration ----------------------------------------
# Anchor to project root so the on-disk counters/catalogs survive restarts
# regardless of the process CWD.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CATALOG_PATH = DATA_DIR / "cta_stop_catalog.json"
CALL_COUNT_PATH = DATA_DIR / "cta_call_count.json"
CATALOG_TTL_SECONDS = 24 * 60 * 60          # rebuild stop catalog daily
NEARBY_CACHE_TTL_SECONDS = 60 * 60          # in-memory nearby lookups
NEARBY_COORD_PRECISION = 3                  # ~110 m grid for cache key
DAILY_CALL_LIMIT = 100_000                  # CTA hard cap
DAILY_CALL_WARN_THRESHOLD = 50_000          # log a warning past this

_gmaps_client: Optional[googlemaps.Client] = None


def _gmaps() -> googlemaps.Client:
    global _gmaps_client
    if _gmaps_client is None:
        _gmaps_client = googlemaps.Client(key=config["google_maps_api_key"])
    return _gmaps_client


# ---------------------------------------------------------------------------
# Low-level CTA API helpers (internal, not exposed as @tool)
# ---------------------------------------------------------------------------


def _today_str() -> str:
    return datetime.now(_timezone.utc).strftime("%Y-%m-%d")


def _record_api_call() -> int:
    """Increment the daily CTA API call counter (UTC day) and return the new total.

    Persists to ``data/cta_call_count.json`` so it survives restarts.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = _today_str()
    state: dict[str, Any] = {"date": today, "count": 0}
    if CALL_COUNT_PATH.exists():
        try:
            loaded = json.loads(CALL_COUNT_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("date") == today:
                state = loaded
        except (json.JSONDecodeError, OSError):
            pass
    state["count"] = int(state.get("count", 0)) + 1
    state["date"] = today
    try:
        CALL_COUNT_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logging.warning(f"Could not persist CTA call counter: {exc}")
    _record_central_api_call("cta_bus")
    count = state["count"]
    if count == DAILY_CALL_WARN_THRESHOLD:
        logging.warning(
            f"CTA API call counter reached {DAILY_CALL_WARN_THRESHOLD} for {today}."
        )
    if count >= DAILY_CALL_LIMIT:
        raise RuntimeError(
            f"CTA daily API quota exhausted ({count}/{DAILY_CALL_LIMIT}). "
            "Try again tomorrow."
        )
    return count


def _api_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET a CTA Bus Tracker endpoint and return the parsed `bustime-response`.

    Raises RuntimeError on transport/HTTP/CTA error.
    """
    api_key = config.get("cta_bus_tracker_api_key")
    if not api_key:
        raise RuntimeError(
            "CTA_BUS_TRACKER_API_KEY is not set in environment / config."
        )
    _record_api_call()
    full_params = {"key": api_key, "format": "json", **params}
    url = f"{CTA_BASE_URL}/{endpoint}"
    safe_params = {k: v for k, v in full_params.items() if k != "key"}
    logged_url = f"{url}?{urlencode({**safe_params, 'key': 'REDACTED'})}"
    logging.info(f"CTA Bus API GET {logged_url}")
    try:
        resp = requests.get(url, params=full_params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"CTA API request to {endpoint} failed: {exc}") from exc

    data = resp.json().get("bustime-response", {})
    logging.info(f"CTA Bus API response from {endpoint}: {data}")
    if "error" in data and not _has_useful_payload(data):
        # All errors and no useful data — surface them.
        msgs = "; ".join(e.get("msg", "") for e in data["error"])
        raise RuntimeError(f"CTA API error from {endpoint}: {msgs}")
    return data


def _has_useful_payload(data: dict[str, Any]) -> bool:
    """True if the response contains any non-error data."""
    return any(k for k in data.keys() if k != "error")


def cta_get_routes() -> list[dict[str, Any]]:
    return _api_get("getroutes", {}).get("routes", []) or []


def cta_get_directions(route: str) -> list[dict[str, Any]]:
    data = _api_get("getdirections", {"rt": route})
    return data.get("directions", []) or []


def cta_get_stops(
    route: Optional[str] = None,
    direction: Optional[str] = None,
    stpids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    if stpids:
        params = {"stpid": ",".join(stpids[:10])}
    elif route and direction:
        params = {"rt": route, "dir": direction}
    else:
        raise ValueError("cta_get_stops requires either stpids or (route AND direction).")
    return _api_get("getstops", params).get("stops", []) or []


def cta_get_predictions(
    stpids: Optional[list[str]] = None,
    routes: Optional[list[str]] = None,
    top: Optional[int] = None,
) -> list[dict[str, Any]]:
    if not stpids:
        raise ValueError("cta_get_predictions requires at least one stop id.")
    params: dict[str, Any] = {"stpid": ",".join(stpids[:10])}
    if routes:
        params["rt"] = ",".join(routes[:10])
    if top:
        params["top"] = int(top)
    return _api_get("getpredictions", params).get("prd", []) or []


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _resolve_location(
    lat: Optional[float], lng: Optional[float], address: Optional[str]
) -> tuple[float, float]:
    if lat is not None and lng is not None:
        return float(lat), float(lng)
    if address:
        results = _gmaps().geocode(address)
        if not results:
            raise ValueError(f"Could not geocode address: {address!r}")
        loc = results[0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    raise ValueError("Provide either (lat AND lng) or an address.")


def _format_predictions(prds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slim the prediction payload to fields the agent / UI cares about."""
    out: list[dict[str, Any]] = []
    for p in prds:
        out.append(
            {
                "stop_id": p.get("stpid"),
                "stop_name": p.get("stpnm"),
                "route": p.get("rt"),
                "route_direction": p.get("rtdir"),
                "destination": p.get("des"),
                "vehicle_id": p.get("vid"),
                "type": "Arrival" if p.get("typ") == "A" else "Departure",
                "predicted_time": p.get("prdtm"),
                "minutes_until": p.get("prdctdn"),
                "delayed": str(p.get("dly", "false")).lower() == "true",
                "passenger_load": p.get("psgld"),
                "dynamic_action": p.get("dyn"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# @tool definitions
# ---------------------------------------------------------------------------


@tool
def get_bus_predictions_for_stop_tool(
    stop_id: Optional[str] = None,
    route: Optional[str] = None,
    direction: Optional[str] = None,
    stop_name: Optional[str] = None,
) -> str | dict[str, Any]:
    """Get predicted arrival/departure times for all CTA buses at a single stop.

    You can identify the stop in either of two ways:
      1. Provide ``stop_id`` (the CTA numeric stpid, e.g. "456"). Easiest.
      2. Provide ``route`` + ``direction`` + ``stop_name`` (case-insensitive
         substring). The tool calls getstops for that route/direction and
         picks the matching stop. If multiple stops match, returns a list of
         candidates and the user must pick one (re-call with a more specific
         ``stop_name`` or with the ``stop_id``).

    The CTA ``direction`` must match the values returned by getdirections for
    that route (e.g. "Eastbound", "Westbound", "Northbound", "Southbound").

    Args:
        stop_id: CTA stop id (stpid). Preferred.
        route: CTA route designator (e.g. "20", "X9"). Required if no stop_id.
        direction: Route direction id (e.g. "Eastbound"). Required if no stop_id.
        stop_name: Substring of the stop's display name. Required if no stop_id.

    Returns:
        A dict with the resolved stop and a list of upcoming bus predictions,
        or a dict with candidate stops if the stop_name was ambiguous.
    """
    try:
        resolved_stop_id = stop_id
        resolved_stop_name: Optional[str] = None

        if not resolved_stop_id:
            if not (route and direction and stop_name):
                return {
                    "error": (
                        "Provide either stop_id, OR all of: route, direction, "
                        "stop_name."
                    )
                }
            stops = cta_get_stops(route=route, direction=direction)
            needle = stop_name.strip().lower()
            matches = [s for s in stops if needle in str(s.get("stpnm", "")).lower()]
            if not matches:
                return {
                    "error": (
                        f"No stops on route {route} ({direction}) matched "
                        f"name containing {stop_name!r}."
                    )
                }
            if len(matches) > 1:
                return {
                    "ambiguous": True,
                    "message": (
                        f"{len(matches)} stops on route {route} ({direction}) "
                        f"match {stop_name!r}. Re-call with a more specific "
                        "stop_name or pass the stop_id."
                    ),
                    "candidates": [
                        {"stop_id": s.get("stpid"), "stop_name": s.get("stpnm")}
                        for s in matches[:25]
                    ],
                }
            resolved_stop_id = str(matches[0].get("stpid"))
            resolved_stop_name = matches[0].get("stpnm")

        prds = cta_get_predictions(stpids=[str(resolved_stop_id)], routes=[route] if route else None)
        formatted = _format_predictions(prds)
        if not resolved_stop_name and formatted:
            resolved_stop_name = formatted[0]["stop_name"]
        result = {
            "stop_id": str(resolved_stop_id),
            "stop_name": resolved_stop_name,
            "prediction_count": len(formatted),
            "predictions": formatted,
        }
        if not formatted:
            result["message"] = (
                "No upcoming bus predictions are currently available for this stop."
            )
        return result
    except Exception as exc:
        logging.exception("get_bus_predictions_for_stop_tool failed")
        return {"error": f"CTA bus prediction lookup failed: {exc}"}


@tool
def get_bus_predictions_near_location_tool(
    route: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    address: Optional[str] = None,
    radius_miles: float = DEFAULT_RADIUS_MILES,
    direction: Optional[str] = None,
) -> str | dict[str, Any]:
    """Get predicted bus times at every stop on a route within a radius of a location.

    The CTA Bus Tracker API does NOT support querying stops by lat/lng directly,
    so this tool:
      1. Calls getdirections for the given route (or uses the supplied direction).
      2. Calls getstops for each direction and filters to stops within
         ``radius_miles`` of the target location.
      3. Calls getpredictions for those stops (in batches of 10) and returns
         the merged predictions.

    Args:
        route: CTA route designator to search (e.g. "20", "X9"). Required.
        lat: Latitude of the target location (decimal degrees). Provide with lng.
        lng: Longitude of the target location (decimal degrees). Provide with lat.
        address: Free-text address to geocode (used if lat/lng not provided).
        radius_miles: Search radius around the location. Default 0.25 miles.
        direction: Optional route direction to restrict to (e.g. "Eastbound").
            If omitted, both directions of the route are searched.

    Returns:
        A dict containing the resolved location, the matching stops, and their
        upcoming bus predictions.
    """
    try:
        if not route:
            return {"error": "route is required."}
        target_lat, target_lng = _resolve_location(lat, lng, address)

        directions = (
            [{"id": direction, "name": direction}]
            if direction
            else cta_get_directions(route)
        )
        if not directions:
            return {"error": f"No directions returned for route {route}."}

        nearby_stops: list[dict[str, Any]] = []
        for d in directions:
            dir_id = d.get("id") or d.get("name")
            if not dir_id:
                continue
            try:
                stops = cta_get_stops(route=route, direction=dir_id)
            except RuntimeError as exc:
                logging.warning(f"getstops failed for {route}/{dir_id}: {exc}")
                continue
            for s in stops:
                slat, slon = s.get("lat"), s.get("lon")
                if slat is None or slon is None:
                    continue
                dist = _haversine_miles(
                    target_lat, target_lng, float(slat), float(slon)
                )
                if dist <= radius_miles:
                    nearby_stops.append(
                        {
                            "stop_id": str(s.get("stpid")),
                            "stop_name": s.get("stpnm"),
                            "direction": dir_id,
                            "lat": float(slat),
                            "lon": float(slon),
                            "distance_miles": round(dist, 3),
                        }
                    )

        nearby_stops.sort(key=lambda s: s["distance_miles"])

        if not nearby_stops:
            return {
                "location": {"lat": target_lat, "lng": target_lng},
                "route": route,
                "radius_miles": radius_miles,
                "stops_found": 0,
                "message": (
                    f"No route {route} stops found within {radius_miles} miles "
                    f"of ({target_lat:.5f}, {target_lng:.5f})."
                ),
            }

        # Batch predictions in groups of 10 (API max).
        all_prds: list[dict[str, Any]] = []
        stop_ids = [s["stop_id"] for s in nearby_stops]
        for i in range(0, len(stop_ids), 10):
            batch = stop_ids[i : i + 10]
            try:
                all_prds.extend(
                    cta_get_predictions(stpids=batch, routes=[route])
                )
            except RuntimeError as exc:
                logging.warning(f"getpredictions failed for batch {batch}: {exc}")

        formatted = _format_predictions(all_prds)
        # Merge distance info into predictions.
        dist_by_stop = {s["stop_id"]: s["distance_miles"] for s in nearby_stops}
        for p in formatted:
            p["distance_miles"] = dist_by_stop.get(str(p.get("stop_id")))
        formatted.sort(key=lambda p: (p.get("distance_miles") or 0, p.get("minutes_until") or "999"))

        return {
            "location": {"lat": target_lat, "lng": target_lng},
            "route": route,
            "radius_miles": radius_miles,
            "stops_found": len(nearby_stops),
            "stops": nearby_stops,
            "prediction_count": len(formatted),
            "predictions": formatted,
        }
    except Exception as exc:
        logging.exception("get_bus_predictions_near_location_tool failed")
        return {"error": f"CTA nearby-bus lookup failed: {exc}"}


# ---------------------------------------------------------------------------
# Stop catalog (full system) + nearby cache for "all routes near me"
# ---------------------------------------------------------------------------


def _load_catalog_from_disk() -> Optional[dict[str, Any]]:
    if not CATALOG_PATH.exists():
        return None
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning(f"Could not read CTA stop catalog: {exc}")
        return None
    fetched_at = data.get("fetched_at", 0)
    if time.time() - float(fetched_at) > CATALOG_TTL_SECONDS:
        return None
    return data


def _save_catalog_to_disk(catalog: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CATALOG_PATH.write_text(json.dumps(catalog), encoding="utf-8")
    except OSError as exc:
        logging.warning(f"Could not persist CTA stop catalog: {exc}")


def cta_get_stop_catalog(force_refresh: bool = False) -> dict[str, Any]:
    """Build (or load from disk) the full system stop catalog.

    Schema::

        {
            "fetched_at": <unix seconds>,
            "stops": [
                {"stop_id": str, "stop_name": str, "lat": float, "lon": float,
                 "route": str, "direction": str},
                ...
            ],
            "routes": [{"rt": str, "rtnm": str, "rtclr": str}, ...],
        }

    Cached on disk for 24h. A cold rebuild makes ~1 + N + (N*D) requests
    (one getroutes, one getdirections per route, one getstops per
    route+direction). Typical N≈130, D≈2 → ~390 calls.
    """
    if not force_refresh:
        cached = _load_catalog_from_disk()
        if cached:
            return cached

    logging.info("Building CTA stop catalog (cold) ...")
    routes = cta_get_routes()
    stops_out: list[dict[str, Any]] = []
    for r in routes:
        rt = r.get("rt")
        if not rt:
            continue
        try:
            dirs = cta_get_directions(rt)
        except RuntimeError as exc:
            logging.warning(f"getdirections failed for {rt}: {exc}")
            continue
        for d in dirs:
            dir_id = d.get("id") or d.get("name")
            if not dir_id:
                continue
            try:
                stops = cta_get_stops(route=rt, direction=dir_id)
            except RuntimeError as exc:
                logging.warning(f"getstops failed for {rt}/{dir_id}: {exc}")
                continue
            for s in stops:
                slat, slon = s.get("lat"), s.get("lon")
                if slat is None or slon is None:
                    continue
                stops_out.append(
                    {
                        "stop_id": str(s.get("stpid")),
                        "stop_name": s.get("stpnm"),
                        "lat": float(slat),
                        "lon": float(slon),
                        "route": rt,
                        "direction": dir_id,
                    }
                )

    catalog = {
        "fetched_at": time.time(),
        "stops": stops_out,
        "routes": routes,
    }
    _save_catalog_to_disk(catalog)
    logging.info(
        f"CTA stop catalog built: {len(stops_out)} stop-direction rows, "
        f"{len(routes)} routes."
    )
    return catalog


# In-memory cache: rounded (lat, lng, radius) -> {"ts": ..., "result": ...}
_nearby_cache: dict[tuple[float, float, float], dict[str, Any]] = {}


def _nearby_cache_key(lat: float, lng: float, radius: float) -> tuple[float, float, float]:
    return (
        round(lat, NEARBY_COORD_PRECISION),
        round(lng, NEARBY_COORD_PRECISION),
        round(radius, 3),
    )


def _stops_within_radius(
    catalog_stops: list[dict[str, Any]],
    lat: float,
    lng: float,
    radius_miles: float,
) -> list[dict[str, Any]]:
    """Bounding-box prefilter then haversine for the survivors."""
    dlat = radius_miles / 69.0
    cos_lat = max(0.0001, math.cos(math.radians(lat)))
    dlng = radius_miles / (69.0 * cos_lat)
    out: list[dict[str, Any]] = []
    for s in catalog_stops:
        if abs(s["lat"] - lat) > dlat or abs(s["lon"] - lng) > dlng:
            continue
        dist = _haversine_miles(lat, lng, s["lat"], s["lon"])
        if dist <= radius_miles:
            row = dict(s)
            row["distance_miles"] = round(dist, 3)
            out.append(row)
    out.sort(key=lambda s: s["distance_miles"])
    return out


@tool
def get_all_nearby_bus_predictions_tool(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    address: Optional[str] = None,
    radius_miles: float = DEFAULT_RADIUS_MILES,
) -> str | dict[str, Any]:
    """Get predicted bus times for ALL CTA routes within a radius of a location.

    Unlike ``get_bus_predictions_near_location_tool`` this does NOT require a
    route. It uses an on-disk 24-hour cached catalog of every CTA stop, finds
    every stop within ``radius_miles`` of the target, then fetches live
    predictions for those stops (batched 10 at a time).

    Use this tool when the user asks "what buses are near me?" / "what routes
    stop near here?" without naming a route.

    Args:
        lat: Latitude of the target location (decimal degrees). Provide with lng.
        lng: Longitude of the target location (decimal degrees). Provide with lat.
        address: Free-text address (used if lat/lng not provided).
        radius_miles: Search radius (default 0.25). Larger values return more
            stops/routes but cost more prediction calls.

    Returns:
        Dict containing the resolved location, the list of nearby stops, the
        unique routes serving them, and live arrival/departure predictions.
    """
    try:
        target_lat, target_lng = _resolve_location(lat, lng, address)
        radius_miles = float(radius_miles)
        cache_key = _nearby_cache_key(target_lat, target_lng, radius_miles)

        # Reuse cached predictions only if very fresh (catalog stops are stable
        # but predictions are not; we only cache the *stops*, not predictions).
        cached = _nearby_cache.get(cache_key)
        nearby_stops: list[dict[str, Any]]
        if cached and (time.time() - cached["ts"]) <= NEARBY_CACHE_TTL_SECONDS:
            nearby_stops = cached["stops"]
            logging.info(f"Nearby cache HIT for {cache_key}: {len(nearby_stops)} stops")
        else:
            catalog = cta_get_stop_catalog()
            nearby_stops = _stops_within_radius(
                catalog["stops"], target_lat, target_lng, radius_miles
            )
            _nearby_cache[cache_key] = {"ts": time.time(), "stops": nearby_stops}
            logging.info(
                f"Nearby cache MISS for {cache_key}: filtered "
                f"{len(catalog['stops'])} stops -> {len(nearby_stops)}"
            )

        if not nearby_stops:
            return {
                "location": {"lat": target_lat, "lng": target_lng},
                "radius_miles": radius_miles,
                "stops_found": 0,
                "routes_found": 0,
                "message": (
                    f"No CTA bus stops found within {radius_miles} miles of "
                    f"({target_lat:.5f}, {target_lng:.5f})."
                ),
            }

        # Unique routes serving those stops (with closest-stop distance).
        routes_summary: dict[str, dict[str, Any]] = {}
        for s in nearby_stops:
            r = s["route"]
            existing = routes_summary.get(r)
            if existing is None or s["distance_miles"] < existing["nearest_distance_miles"]:
                routes_summary[r] = {
                    "route": r,
                    "nearest_stop_id": s["stop_id"],
                    "nearest_stop_name": s["stop_name"],
                    "nearest_distance_miles": s["distance_miles"],
                }
        routes_list = sorted(
            routes_summary.values(), key=lambda x: x["nearest_distance_miles"]
        )

        # De-dup stop ids (a single stop_id may appear for multiple directions
        # of the same route in the catalog).
        unique_stop_ids: list[str] = []
        seen: set[str] = set()
        for s in nearby_stops:
            if s["stop_id"] not in seen:
                seen.add(s["stop_id"])
                unique_stop_ids.append(s["stop_id"])

        # Live predictions, batched 10 at a time.
        all_prds: list[dict[str, Any]] = []
        for i in range(0, len(unique_stop_ids), 10):
            batch = unique_stop_ids[i : i + 10]
            try:
                all_prds.extend(cta_get_predictions(stpids=batch))
            except RuntimeError as exc:
                logging.warning(f"getpredictions failed for batch {batch}: {exc}")

        formatted = _format_predictions(all_prds)
        # Attach distance info to each prediction.
        dist_by_stop: dict[str, float] = {}
        for s in nearby_stops:
            sid = s["stop_id"]
            if sid not in dist_by_stop or s["distance_miles"] < dist_by_stop[sid]:
                dist_by_stop[sid] = s["distance_miles"]
        for p in formatted:
            p["distance_miles"] = dist_by_stop.get(str(p.get("stop_id")))
        formatted.sort(
            key=lambda p: (p.get("distance_miles") or 0, p.get("minutes_until") or "999")
        )

        return {
            "location": {"lat": target_lat, "lng": target_lng},
            "radius_miles": radius_miles,
            "stops_found": len(unique_stop_ids),
            "routes_found": len(routes_list),
            "routes": routes_list,
            "stops": nearby_stops,
            "prediction_count": len(formatted),
            "predictions": formatted,
        }
    except Exception as exc:
        logging.exception("get_all_nearby_bus_predictions_tool failed")
        return {"error": f"CTA all-nearby lookup failed: {exc}"}
