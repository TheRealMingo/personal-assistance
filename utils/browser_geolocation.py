"""Mobile-friendly browser-geolocation widget for Streamlit pages.

The default ``streamlit-geolocation`` button is tiny, lives inside an
iframe, and frequently does nothing on mobile (especially when the page
is served over plain HTTP from a dev machine). This helper renders a
normal ``st.button`` and, on click, asks the browser for coordinates via
``streamlit_js_eval.get_geolocation`` (which uses ``navigator.geolocation``
directly). It also surfaces an explicit warning when the page is not in
a secure context (HTTPS or ``localhost``), which is the #1 reason
geolocation silently fails on phones.

Coordinates are cached in ``st.session_state["browser_geo"]`` so other
forms on the page can consume them.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import streamlit as st

logger = logging.getLogger(__name__)

try:
    from streamlit_js_eval import get_geolocation, streamlit_js_eval
except ImportError:  # pragma: no cover - graceful fallback
    get_geolocation = None  # type: ignore[assignment]
    streamlit_js_eval = None  # type: ignore[assignment]

try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:  # pragma: no cover
    streamlit_geolocation = None  # type: ignore[assignment]


SESSION_KEY = "browser_geo"


def _warn_if_insecure(key_prefix: str) -> None:
    """Show a warning if the page is not on HTTPS / localhost.

    ``navigator.geolocation`` is blocked by every modern mobile browser
    on insecure origins, so this is almost always the cause when the
    button "does nothing" on a phone.
    """
    if streamlit_js_eval is None:
        return
    try:
        is_secure = streamlit_js_eval(
            js_expressions="window.isSecureContext",
            key=f"{key_prefix}_is_secure_ctx",
            want_output=True,
        )
    except Exception:
        is_secure = None
    if is_secure is False:
        st.warning(
            "📍 This page is not served over HTTPS, so browsers will "
            "block the location request. Open the app on `localhost` or "
            "behind HTTPS (e.g. via Cloudflare Tunnel / ngrok / a reverse "
            "proxy) to use the location button."
        )


def _store_coords(coords: dict[str, Any]) -> None:
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    if lat is None or lng is None:
        logger.warning("Received coords dict missing latitude/longitude; ignoring.")
        return
    st.session_state[SESSION_KEY] = {
        "lat": float(lat),
        "lng": float(lng),
        "accuracy": coords.get("accuracy"),
    }
    logger.info(f"Browser location stored: lat={lat}, lng={lng}, accuracy={coords.get('accuracy')}")


def render_browser_location_widget(key_prefix: str = "geo") -> Optional[dict[str, Any]]:
    """Render a tap-friendly "Get my current location" control.

    Returns the cached ``{"lat", "lng", "accuracy"}`` dict (or ``None``).
    Side effect: writes to ``st.session_state["browser_geo"]``.
    """
    _warn_if_insecure(key_prefix)

    request_key = f"{key_prefix}_request_geo"
    if request_key not in st.session_state:
        st.session_state[request_key] = False

    cols = st.columns([1, 1])
    with cols[0]:
        if st.button(
            "📍 Use my location",
            key=f"{key_prefix}_get_loc_btn",
            width='stretch',
        ):
            st.session_state[request_key] = True
    with cols[1]:
        if st.button(
            "Clear location",
            key=f"{key_prefix}_clear_loc_btn",
            width='stretch',
        ):
            st.session_state.pop(SESSION_KEY, None)
            st.session_state[request_key] = False

    if st.session_state[request_key]:
        if get_geolocation is None:
            st.error(
                "`streamlit-js-eval` is not installed. Run "
                "`pip install streamlit-js-eval` to enable the location button."
            )
            st.session_state[request_key] = False
        else:
            with st.spinner("Waiting for browser permission…"):
                geo = get_geolocation()
            # streamlit-js-eval returns either {"coords": {...}, ...}
            # or a flattened dict depending on version. Handle both.
            if isinstance(geo, dict):
                coords = geo.get("coords") if isinstance(geo.get("coords"), dict) else geo
                if coords and coords.get("latitude") is not None:
                    _store_coords(coords)
                    st.session_state[request_key] = False

    # Legacy fallback: if streamlit-js-eval is missing, expose the old
    # streamlit-geolocation button so desktop users aren't blocked.
    if get_geolocation is None and streamlit_geolocation is not None:
        st.caption("Fallback widget (desktop only):")
        legacy = streamlit_geolocation()
        if (
            isinstance(legacy, dict)
            and legacy.get("latitude") is not None
            and legacy.get("longitude") is not None
        ):
            _store_coords(
                {
                    "latitude": legacy["latitude"],
                    "longitude": legacy["longitude"],
                    "accuracy": legacy.get("accuracy"),
                }
            )

    cached = st.session_state.get(SESSION_KEY)
    if cached:
        acc = cached.get("accuracy")
        acc_txt = f" (±{acc:.0f} m)" if isinstance(acc, (int, float)) else ""
        st.success(
            f"Using browser location: {cached['lat']:.5f}, "
            f"{cached['lng']:.5f}{acc_txt}"
        )
    elif st.session_state[request_key]:
        st.info(
            "If nothing happens, check that you allowed location permission "
            "for this site in your browser settings."
        )
    else:
        st.info("No browser location captured yet. Tap the button above.")
    return cached
