"""CTA Train Tracker API tools.

Exposes two LangChain ``@tool`` functions plus internal helpers for the CTA
Train Tracker v1 REST API:

    - get_train_arrivals_for_station_tool: arrivals for a single station, by
      mapid OR by station name.
    - get_all_nearby_train_arrivals_tool: arrivals for ALL stations whose
      coordinates fall within a radius of a lat/lng or address.

Because the Train Tracker API has no endpoint that returns station
coordinates, we build a station catalog from the Chicago Data Portal's
"CTA - System Information - List of 'L' Stops" dataset
(https://data.cityofchicago.org/resource/8pix-ypme.json) and cache it on
disk for 30 days. That request does NOT count against the CTA quota.

Reference: cta_Train_Tracker_API_Developer_Guide_and_Documentation.md
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

TRAIN_BASE_URL = "https://lapi.transitchicago.com/api/1.0"
TRAIN_ARRIVALS_ENDPOINT = "ttarrivals.aspx"
DEFAULT_RADIUS_MILES = 0.5
EARTH_RADIUS_MILES = 3958.7613

# --- Quota / caching configuration ----------------------------------------
# Anchor to project root so the on-disk counters/catalogs survive restarts
# regardless of the process CWD.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRAIN_CATALOG_PATH = DATA_DIR / "cta_train_station_catalog.json"
TRAIN_CALL_COUNT_PATH = DATA_DIR / "cta_train_call_count.json"
TRAIN_CATALOG_TTL_SECONDS = 30 * 24 * 60 * 60   # station catalog rarely changes
NEARBY_CACHE_TTL_SECONDS = 60 * 60              # in-memory nearby lookups
NEARBY_COORD_PRECISION = 3                      # ~110 m grid for cache key
TRAIN_DAILY_CALL_LIMIT = 50_000                 # user-specified cap
TRAIN_DAILY_CALL_WARN_THRESHOLD = 25_000

CHICAGO_DATA_PORTAL_L_STOPS_URL = (
    "https://data.cityofchicago.org/resource/8pix-ypme.json"
)

# Map of Data-Portal route boolean column -> CTA Train API rt code + display
# name. The rt codes match the values returned in arrivals' ``rt`` field.
ROUTE_COLUMN_TO_CTA: dict[str, dict[str, str]] = {
    "red":  {"rt": "Red",  "name": "Red Line"},
    "blue": {"rt": "Blue", "name": "Blue Line"},
    "g":    {"rt": "G",    "name": "Green Line"},
    "brn":  {"rt": "Brn",  "name": "Brown Line"},
    "p":    {"rt": "P",    "name": "Purple Line"},
    "pexp": {"rt": "Pexp", "name": "Purple Line Express"},
    "y":    {"rt": "Y",    "name": "Yellow Line"},
    "pnk":  {"rt": "Pink", "name": "Pink Line"},
    "o":    {"rt": "Org",  "name": "Orange Line"},
}

_gmaps_client: Optional[googlemaps.Client] = None


def _gmaps() -> googlemaps.Client:
    global _gmaps_client
    if _gmaps_client is None:
        _gmaps_client = googlemaps.Client(key=config["google_maps_api_key"])
    return _gmaps_client


# ---------------------------------------------------------------------------
# Quota counter (separate from the bus counter)
# ---------------------------------------------------------------------------


def _today_str() -> str:
    return datetime.now(_timezone.utc).strftime("%Y-%m-%d")


def _record_train_api_call() -> int:
    """Increment the daily Train Tracker call counter (UTC day)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = _today_str()
    state: dict[str, Any] = {"date": today, "count": 0}
    if TRAIN_CALL_COUNT_PATH.exists():
        try:
            loaded = json.loads(TRAIN_CALL_COUNT_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("date") == today:
                state = loaded
        except (json.JSONDecodeError, OSError):
            pass
    state["count"] = int(state.get("count", 0)) + 1
    state["date"] = today
    try:
        TRAIN_CALL_COUNT_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logging.warning(f"Could not persist CTA Train call counter: {exc}")
    _record_central_api_call("cta_train")
    count = state["count"]
    if count == TRAIN_DAILY_CALL_WARN_THRESHOLD:
        logging.warning(
            f"CTA Train API call counter reached {TRAIN_DAILY_CALL_WARN_THRESHOLD} "
            f"for {today}."
        )
    if count >= TRAIN_DAILY_CALL_LIMIT:
        raise RuntimeError(
            f"CTA Train daily API quota exhausted "
            f"({count}/{TRAIN_DAILY_CALL_LIMIT}). Try again tomorrow."
        )
    return count


# ---------------------------------------------------------------------------
# Low-level Train Tracker API
# ---------------------------------------------------------------------------


def _train_api_get(
    endpoint: str, params: dict[str, Any]
) -> dict[str, Any]:
    """GET a Train Tracker endpoint and return the parsed ``ctatt`` body.

    Raises RuntimeError on transport/HTTP/CTA error.
    """
    api_key = config.get("cta_train_tracker_api_key")
    if not api_key:
        raise RuntimeError(
            "CTA_TRAIN_TRACKER_API_KEY is not set in environment / config."
        )
    _record_train_api_call()
    full_params = {"key": api_key, "outputType": "JSON", **params}
    url = f"{TRAIN_BASE_URL}/{endpoint}"
    safe_params = {k: v for k, v in full_params.items() if k != "key"}
    logged_url = f"{url}?{urlencode({**safe_params, 'key': 'REDACTED'})}"
    logging.info(f"CTA Train API GET {logged_url}")
    try:
        resp = requests.get(url, params=full_params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"CTA Train API request to {endpoint} failed: {exc}"
        ) from exc

    body = resp.json().get("ctatt", {})
    logging.info(f"CTA Train API response from {endpoint}: {body}")
    err_code = str(body.get("errCd", "0"))
    err_msg = body.get("errNm")
    if err_code != "0" and not body.get("eta"):
        raise RuntimeError(
            f"CTA Train API error {err_code} from {endpoint}: {err_msg}"
        )
    return body


def cta_get_train_arrivals(
    mapid: Optional[str] = None,
    stpid: Optional[str] = None,
    route: Optional[str] = None,
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    """Call ttarrivals.aspx and return the raw ``ctatt`` body."""
    if not mapid and not stpid:
        raise ValueError("cta_get_train_arrivals requires mapid or stpid.")
    params: dict[str, Any] = {}
    if mapid:
        params["mapid"] = str(mapid)
    if stpid:
        params["stpid"] = str(stpid)
    if route:
        params["rt"] = route
    if max_results:
        params["max"] = int(max_results)
    return _train_api_get(TRAIN_ARRIVALS_ENDPOINT, params)


# ---------------------------------------------------------------------------
# Geo helpers (mirrors cta_bus_tool)
# ---------------------------------------------------------------------------


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
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


# ---------------------------------------------------------------------------
# Station catalog (Chicago Data Portal — does NOT count against CTA quota)
# ---------------------------------------------------------------------------


def _load_train_catalog_from_disk() -> Optional[dict[str, Any]]:
    if not TRAIN_CATALOG_PATH.exists():
        return None
    try:
        data = json.loads(TRAIN_CATALOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning(f"Could not read CTA Train station catalog: {exc}")
        return None
    if time.time() - float(data.get("fetched_at", 0)) > TRAIN_CATALOG_TTL_SECONDS:
        return None
    return data


def _save_train_catalog_to_disk(catalog: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        TRAIN_CATALOG_PATH.write_text(json.dumps(catalog), encoding="utf-8")
    except OSError as exc:
        logging.warning(f"Could not persist CTA Train station catalog: {exc}")


def _parse_data_portal_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert a Data Portal 'L' stops row into our normalized stop entry."""
    loc = row.get("location") or {}
    # location may be a dict {"latitude": "...", "longitude": "...", "human_address": "..."}
    # OR it may be missing — the dataset also has top-level lat/lon string fields.
    lat = loc.get("latitude") if isinstance(loc, dict) else None
    lon = loc.get("longitude") if isinstance(loc, dict) else None
    if lat is None:
        lat = row.get("latitude")
    if lon is None:
        lon = row.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    routes: list[str] = []
    for col, info in ROUTE_COLUMN_TO_CTA.items():
        val = row.get(col)
        if str(val).lower() == "true":
            routes.append(info["rt"])
    return {
        "stop_id": str(row.get("stop_id") or ""),
        "stop_name": row.get("stop_name") or row.get("station_name") or "",
        "station_id": str(row.get("map_id") or ""),
        "station_name": row.get("station_name") or "",
        "station_descriptive_name": row.get("station_descriptive_name") or "",
        "direction_id": row.get("direction_id"),
        "ada": str(row.get("ada", "")).lower() == "true",
        "lat": lat_f,
        "lon": lon_f,
        "routes": routes,
    }


def cta_get_train_station_catalog(force_refresh: bool = False) -> dict[str, Any]:
    """Build (or load from disk) the CTA 'L' station catalog.

    Schema::

        {
            "fetched_at": <unix seconds>,
            "stops":   [<one entry per platform>, ...],
            "stations": [<one entry per parent station, deduped by map_id>, ...],
        }

    Cached on disk for 30 days. The fetch hits the Chicago Data Portal, NOT
    the CTA Train Tracker API, so it does NOT consume the daily quota.
    """
    if not force_refresh:
        cached = _load_train_catalog_from_disk()
        if cached:
            return cached

    logging.info("Fetching CTA Train station catalog from Chicago Data Portal ...")
    catalog_url = f"{CHICAGO_DATA_PORTAL_L_STOPS_URL}?{urlencode({'$limit': 1000})}"
    logging.info(f"CTA Train station catalog URL: {catalog_url}")
    try:
        # Default page size on Data Portal is 1000; the dataset has ~300 rows.
        resp = requests.get(
            CHICAGO_DATA_PORTAL_L_STOPS_URL,
            params={"$limit": 1000},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        logging.info(f"CTA Train station catalog response: {len(rows)} rows received")
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not fetch CTA L stops from Chicago Data Portal: {exc}"
        ) from exc

    stops: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_data_portal_row(row)
        if parsed:
            stops.append(parsed)

    # Dedupe to station level by map_id, taking union of routes across platforms.
    stations: dict[str, dict[str, Any]] = {}
    for s in stops:
        sid = s["station_id"]
        if not sid:
            continue
        existing = stations.get(sid)
        if existing is None:
            stations[sid] = {
                "station_id": sid,
                "station_name": s["station_name"],
                "station_descriptive_name": s["station_descriptive_name"],
                "lat": s["lat"],
                "lon": s["lon"],
                "ada": s["ada"],
                "routes": list(s["routes"]),
            }
        else:
            for r in s["routes"]:
                if r not in existing["routes"]:
                    existing["routes"].append(r)
            existing["ada"] = existing["ada"] or s["ada"]

    catalog = {
        "fetched_at": time.time(),
        "stops": stops,
        "stations": list(stations.values()),
    }
    _save_train_catalog_to_disk(catalog)
    logging.info(
        f"CTA Train station catalog built: {len(stops)} stops, "
        f"{len(stations)} stations."
    )
    return catalog


# ---------------------------------------------------------------------------
# Nearby filter + in-memory cache
# ---------------------------------------------------------------------------


_nearby_cache: dict[tuple[float, float, float], dict[str, Any]] = {}


def _nearby_cache_key(
    lat: float, lng: float, radius: float
) -> tuple[float, float, float]:
    return (
        round(lat, NEARBY_COORD_PRECISION),
        round(lng, NEARBY_COORD_PRECISION),
        round(radius, 3),
    )


def _stations_within_radius(
    stations: list[dict[str, Any]],
    lat: float,
    lng: float,
    radius_miles: float,
) -> list[dict[str, Any]]:
    """Bounding-box prefilter then haversine for the survivors."""
    dlat = radius_miles / 69.0
    cos_lat = max(0.0001, math.cos(math.radians(lat)))
    dlng = radius_miles / (69.0 * cos_lat)
    out: list[dict[str, Any]] = []
    for s in stations:
        if abs(s["lat"] - lat) > dlat or abs(s["lon"] - lng) > dlng:
            continue
        dist = _haversine_miles(lat, lng, s["lat"], s["lon"])
        if dist <= radius_miles:
            row = dict(s)
            row["distance_miles"] = round(dist, 3)
            out.append(row)
    out.sort(key=lambda s: s["distance_miles"])
    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _parse_cta_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """Parse a Train Tracker timestamp.

    The XML docs show ``yyyyMMdd HH:mm:ss`` (e.g. ``20110321 18:34:29``) but
    the JSON variant returns ISO 8601 (e.g. ``2026-05-13T18:34:29``). Both
    are local Chicago time. Accept either.
    """
    if not ts or not isinstance(ts, str):
        return None
    candidates = (
        "%Y%m%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _minutes_until(prdt: Optional[str], arrt: Optional[str]) -> Optional[int]:
    """Whole minutes between prdt (prediction generated) and arrT (arrival)."""
    p = _parse_cta_timestamp(prdt)
    a = _parse_cta_timestamp(arrt)
    if p is None or a is None:
        return None
    delta = (a - p).total_seconds()
    return max(0, int(round(delta / 60.0)))


def _format_arrivals(etas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slim the arrival payload to fields the agent / UI cares about."""
    out: list[dict[str, Any]] = []
    for e in etas:
        is_app = str(e.get("isApp", "0")) == "1"
        is_sch = str(e.get("isSch", "0")) == "1"
        is_dly = str(e.get("isDly", "0")) == "1"
        is_flt = str(e.get("isFlt", "0")) == "1"
        mins = _minutes_until(e.get("prdt"), e.get("arrT"))
        if mins is None:
            mins_label: Any = None
        elif is_app or mins <= 0:
            mins_label = "Due"
        else:
            mins_label = mins
        out.append(
            {
                "station_id": str(e.get("staId") or ""),
                "stop_id": str(e.get("stpId") or ""),
                "station_name": e.get("staNm"),
                "platform": e.get("stpDe"),
                "run_number": e.get("rn"),
                "route": e.get("rt"),
                "destination": e.get("destNm"),
                "destination_stop_id": str(e.get("destSt") or ""),
                "predicted_at": e.get("prdt"),
                "arrival_time": e.get("arrT"),
                "minutes_until": mins_label,
                "approaching": is_app,
                "scheduled": is_sch,
                "delayed": is_dly,
                "fault": is_flt,
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "heading": e.get("heading"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# @tool definitions
# ---------------------------------------------------------------------------


@tool
def get_train_arrivals_for_station_tool(
    station_id: Optional[str] = None,
    station_name: Optional[str] = None,
    route: Optional[str] = None,
    max_results: Optional[int] = None,
) -> str | dict[str, Any]:
    """Get predicted arrival times for all CTA trains at a single station.

    You can identify the station in either of two ways:
      1. Provide ``station_id`` (the CTA five-digit ``mapid``, e.g. "40380").
         Preferred.
      2. Provide ``station_name`` (case-insensitive substring of the station
         name, e.g. "clark/lake"). The tool consults a cached station catalog
         and resolves the matching station. If multiple stations match, it
         returns ``{"ambiguous": true, "candidates": [...]}`` and the caller
         should re-invoke with a narrower name or with ``station_id``.

    Optional filters:
        route: One of "Red", "Blue", "G", "Brn", "P", "Pexp", "Y", "Pink",
            "Org" — restricts results to a single line.
        max_results: Max arrivals to return (CTA returns all platforms by
            default).

    Returns:
        Dict with the resolved station, the time CTA generated the response,
        and a list of arrival predictions. ``minutes_until`` is either an
        integer or the string "Due".
    """
    try:
        resolved_mapid = (station_id or "").strip() or None
        resolved_name: Optional[str] = None
        resolved_routes: Optional[list[str]] = None

        if not resolved_mapid:
            if not station_name:
                return {
                    "error": "Provide either station_id (mapid) or station_name."
                }
            catalog = cta_get_train_station_catalog()
            needle = station_name.strip().lower()
            matches = [
                s for s in catalog["stations"]
                if needle in str(s.get("station_name", "")).lower()
                or needle in str(s.get("station_descriptive_name", "")).lower()
            ]
            if not matches:
                return {
                    "error": (
                        f"No CTA train station name matched "
                        f"{station_name!r}."
                    )
                }
            if len(matches) > 1:
                return {
                    "ambiguous": True,
                    "message": (
                        f"{len(matches)} stations matched {station_name!r}. "
                        "Re-call with a more specific name or pass station_id."
                    ),
                    "candidates": [
                        {
                            "station_id": s["station_id"],
                            "station_name": s["station_name"],
                            "routes": s["routes"],
                        }
                        for s in matches[:25]
                    ],
                }
            chosen = matches[0]
            resolved_mapid = chosen["station_id"]
            resolved_name = chosen["station_name"]
            resolved_routes = chosen["routes"]

        body = cta_get_train_arrivals(
            mapid=resolved_mapid, route=route, max_results=max_results
        )
        etas = body.get("eta") or []
        if isinstance(etas, dict):  # CTA sometimes returns a single dict
            etas = [etas]
        formatted = _format_arrivals(etas)
        if not resolved_name and formatted:
            resolved_name = formatted[0].get("station_name")
        result: dict[str, Any] = {
            "station_id": str(resolved_mapid),
            "station_name": resolved_name,
            "served_routes": resolved_routes,
            "response_generated_at": body.get("tmst"),
            "prediction_count": len(formatted),
            "predictions": formatted,
        }
        if not formatted:
            result["message"] = (
                "No upcoming train arrivals are currently available for this "
                "station."
            )
        return result
    except Exception as exc:
        logging.exception("get_train_arrivals_for_station_tool failed")
        return {"error": f"CTA train arrival lookup failed: {exc}"}


@tool
def get_all_nearby_train_arrivals_tool(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    address: Optional[str] = None,
    radius_miles: float = DEFAULT_RADIUS_MILES,
) -> str | dict[str, Any]:
    """Get predicted arrival times for ALL CTA trains within a radius of a location.

    The CTA Train Tracker API does not accept lat/lng input, so this tool:
      1. Loads the cached 'L' station catalog (Chicago Data Portal).
      2. Filters stations within ``radius_miles`` of the target.
      3. Calls ttarrivals once per nearby station and merges results.

    Each nearby station costs one Train Tracker API call. With the default
    radius of 0.5 miles you typically hit 1-3 stations.

    Args:
        lat: Latitude of the target location (decimal degrees). Provide with lng.
        lng: Longitude of the target location (decimal degrees). Provide with lat.
        address: Free-text address (used if lat/lng not provided).
        radius_miles: Search radius. Default 0.5.

    Returns:
        Dict containing the resolved location, the matching stations, the
        unique routes serving them, and live arrival predictions.
    """
    try:
        target_lat, target_lng = _resolve_location(lat, lng, address)
        radius_miles = float(radius_miles)
        cache_key = _nearby_cache_key(target_lat, target_lng, radius_miles)

        cached = _nearby_cache.get(cache_key)
        nearby_stations: list[dict[str, Any]]
        if cached and (time.time() - cached["ts"]) <= NEARBY_CACHE_TTL_SECONDS:
            nearby_stations = cached["stations"]
            logging.info(
                f"Train nearby cache HIT for {cache_key}: "
                f"{len(nearby_stations)} stations"
            )
        else:
            catalog = cta_get_train_station_catalog()
            nearby_stations = _stations_within_radius(
                catalog["stations"], target_lat, target_lng, radius_miles
            )
            _nearby_cache[cache_key] = {
                "ts": time.time(), "stations": nearby_stations
            }
            logging.info(
                f"Train nearby cache MISS for {cache_key}: filtered "
                f"{len(catalog['stations'])} stations -> {len(nearby_stations)}"
            )

        if not nearby_stations:
            return {
                "location": {"lat": target_lat, "lng": target_lng},
                "radius_miles": radius_miles,
                "stations_found": 0,
                "routes_found": 0,
                "message": (
                    f"No CTA 'L' stations found within {radius_miles} miles of "
                    f"({target_lat:.5f}, {target_lng:.5f})."
                ),
            }

        # Unique routes served by those stations.
        routes_summary: dict[str, dict[str, Any]] = {}
        for s in nearby_stations:
            for r in s.get("routes", []):
                existing = routes_summary.get(r)
                if (
                    existing is None
                    or s["distance_miles"] < existing["nearest_distance_miles"]
                ):
                    routes_summary[r] = {
                        "route": r,
                        "nearest_station_id": s["station_id"],
                        "nearest_station_name": s["station_name"],
                        "nearest_distance_miles": s["distance_miles"],
                    }
        routes_list = sorted(
            routes_summary.values(), key=lambda x: x["nearest_distance_miles"]
        )

        all_predictions: list[dict[str, Any]] = []
        per_station: list[dict[str, Any]] = []
        for stn in nearby_stations:
            try:
                body = cta_get_train_arrivals(mapid=stn["station_id"])
            except RuntimeError as exc:
                logging.warning(
                    f"ttarrivals failed for station {stn['station_id']}: {exc}"
                )
                per_station.append(
                    {
                        "station_id": stn["station_id"],
                        "station_name": stn["station_name"],
                        "distance_miles": stn["distance_miles"],
                        "error": str(exc),
                    }
                )
                continue
            etas = body.get("eta") or []
            if isinstance(etas, dict):
                etas = [etas]
            formatted = _format_arrivals(etas)
            for p in formatted:
                p["distance_miles"] = stn["distance_miles"]
            per_station.append(
                {
                    "station_id": stn["station_id"],
                    "station_name": stn["station_name"],
                    "distance_miles": stn["distance_miles"],
                    "prediction_count": len(formatted),
                }
            )
            all_predictions.extend(formatted)

        all_predictions.sort(
            key=lambda p: (
                p.get("distance_miles") or 0,
                # "Due" sorts before any number
                0 if p.get("minutes_until") == "Due" else (p.get("minutes_until") or 999),
            )
        )

        return {
            "location": {"lat": target_lat, "lng": target_lng},
            "radius_miles": radius_miles,
            "stations_found": len(nearby_stations),
            "routes_found": len(routes_list),
            "routes": routes_list,
            "stations": [
                {
                    "station_id": s["station_id"],
                    "station_name": s["station_name"],
                    "station_descriptive_name": s["station_descriptive_name"],
                    "lat": s["lat"],
                    "lon": s["lon"],
                    "ada": s["ada"],
                    "routes": s["routes"],
                    "distance_miles": s["distance_miles"],
                }
                for s in nearby_stations
            ],
            "per_station_summary": per_station,
            "prediction_count": len(all_predictions),
            "predictions": all_predictions,
        }
    except Exception as exc:
        logging.exception("get_all_nearby_train_arrivals_tool failed")
        return {"error": f"CTA nearby-train lookup failed: {exc}"}
