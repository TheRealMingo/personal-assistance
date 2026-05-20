"""Browser-notification helper used across Streamlit pages.

Injects a small JS snippet that:
- Requests notification permission once.
- On a short interval, checks the current local time against the configured
  morning and evening routine times and fires a desktop notification once per
  day per period when those minutes match.

Only runs while the assistant page is open in a browser tab.
"""

from __future__ import annotations

import json
import logging

import streamlit as st

from config.runtime_settings import load_settings

logger = logging.getLogger(__name__)


def render_notification_bridge() -> None:
    """Render the JS bridge for browser notifications, if enabled."""
    settings = load_settings()
    if not settings.get("browser_notifications_enabled"):
        logger.debug("Browser notifications disabled; skipping notification bridge.")
        return

    payload = {
        "morning": settings.get("morning_routine_time", "07:00"),
        "evening": settings.get("evening_routine_time", "21:00"),
    }
    logger.debug(f"Rendering notification bridge with payload: {payload}")
    js = """
    <script>
    (function() {
        const cfg = __PAYLOAD__;
        if (!('Notification' in window)) { return; }
        if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
        function checkReminders() {
            try {
                if (Notification.permission !== 'granted') { return; }
                const now = new Date();
                const hh = String(now.getHours()).padStart(2, '0');
                const mm = String(now.getMinutes()).padStart(2, '0');
                const current = hh + ':' + mm;
                const todayKey = now.toISOString().slice(0, 10);
                if (current === cfg.morning) {
                    const k = 'pa_notif_morning_' + todayKey;
                    if (!localStorage.getItem(k)) {
                        new Notification('Good morning ☀️', {
                            body: "Time for your morning routine."
                        });
                        localStorage.setItem(k, '1');
                    }
                }
                if (current === cfg.evening) {
                    const k = 'pa_notif_evening_' + todayKey;
                    if (!localStorage.getItem(k)) {
                        new Notification('Good evening 🌙', {
                            body: "Time for your evening routine."
                        });
                        localStorage.setItem(k, '1');
                    }
                }
            } catch (e) { console.warn('notif check error', e); }
        }
        checkReminders();
        if (!window.__paNotifTimer) {
            window.__paNotifTimer = setInterval(checkReminders, 30000);
        }
    })();
    </script>
    """.replace("__PAYLOAD__", json.dumps(payload))
    st.iframe(js, height=1)


def render_cta_arrival_notifications(
    predictions: list[dict],
    threshold_minutes: int,
    transit_type: str = "bus",
) -> None:
    """Inject JS browser notifications for CTA arrivals at or below *threshold_minutes*.

    Only fires when browser notifications are enabled in settings.
    Deduplicates via localStorage so the same arrival does not fire twice
    across auto-refresh cycles.
    """
    settings = load_settings()
    if not settings.get("browser_notifications_enabled"):
        logger.debug("Browser notifications disabled; skipping CTA arrival notifications.")
        return
    if not predictions or threshold_minutes <= 0:
        return

    notif_items: list[dict] = []
    for p in predictions:
        mins = p.get("minutes_until")
        if mins is None:
            continue
        try:
            mins_int = int(mins)
        except (ValueError, TypeError):
            continue
        if mins_int > threshold_minutes:
            continue

        route = p.get("route") or "?"
        dest = p.get("destination") or route

        if transit_type == "train":
            location = p.get("station_name") or str(p.get("station_id") or "")
            dedup_key = (
                f"pa_cta_train_{p.get('station_id', '')}_{route}"
                f"_{p.get('arrival_time', '')}"
            )
            title = "🚆 Train arriving soon"
        else:
            location = p.get("stop_name") or str(p.get("stop_id") or "")
            dedup_key = (
                f"pa_cta_bus_{p.get('stop_id', '')}_{route}"
                f"_{p.get('predicted_time', '')}"
            )
            title = "🚌 Bus arriving soon"

        body = f"{route} to {dest} in {mins_int} min"
        if location:
            body += f" at {location}"

        notif_items.append({"title": title, "body": body, "key": dedup_key})

    if not notif_items:
        return

    logger.debug(f"Injecting CTA arrival notifications for {len(notif_items)} prediction(s).")
    js = """
    (function() {
        if (!('Notification' in window)) { return; }
        if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
        if (Notification.permission !== 'granted') { return; }
        var items = __ITEMS__;
        items.forEach(function(n) {
            if (!localStorage.getItem(n.key)) {
                new Notification(n.title, { body: n.body });
                localStorage.setItem(n.key, '1');
            }
        });
    })();
    </script>
    """.replace("__ITEMS__", json.dumps(notif_items))
    st.iframe(js, height=1)
