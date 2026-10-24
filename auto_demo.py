#!/usr/bin/env python3
"""Continuous TerminalVector show director with a ten-second manual override."""
import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("TERMINALVECTOR_URL", "http://127.0.0.1:8080")
HEADLESS = os.environ.get("TERMINALVECTOR_HEADLESS") == "1"
last_headless_switch = 0.0


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=body,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_backend(timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request("/health")
            return
        except (OSError, urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise SystemExit("TerminalVector backend did not become ready at " + BASE_URL)


def dispatch(label, action, payload=None, delay=3.2):
    request("/api/demo/action", {"action": action, **(payload or {})})
    print("[TerminalVector demo] " + label, flush=True)
    time.sleep(delay)


def wait_for_director():
    """Hold the automated director while a person is using either window."""
    global last_headless_switch
    while True:
        state = request("/api/state")
        now = time.time()
        remaining = float(state.get("automation_override_until", 0)) - now
        if remaining <= 0:
            if HEADLESS and now - last_headless_switch >= 15:
                try:
                    request("/api/next", {})
                    last_headless_switch = now
                    print("[TerminalVector demo] Cycling to the next video scenario", flush=True)
                except urllib.error.HTTPError as exc:
                    if exc.code != 409:
                        raise
            return state
        time.sleep(min(0.5, remaining))


def all_windows_closed_since(state, first_seen):
    if HEADLESS:
        return False, first_seen
    now = time.time()
    clients = state.get("clients", {})
    active = any(now - float(clients.get(name, 0)) < 8 for name in ("controller", "obs"))
    if active:
        return False, now
    if first_seen is None:
        return False, None
    return now - first_seen >= 16, first_seen


def main():
    wait_for_backend()
    print("[TerminalVector demo] Continuous show is running. Click any window to take manual control for 10 seconds.", flush=True)
    first_seen = None
    cycle = 0
    chat_messages = [
        ("AeroSpotter88", "That departure is so smooth!"),
        ("PlaneWatcher", "Great view of the runway today."),
        ("RunwayFan", "Love seeing the traffic at LAX."),
        ("JetStreamJess", "Camera two has a great angle."),
        ("CloudNine", "Thanks for the live coverage!"),
        ("AeroSpotter88", "Look at that clean approach."),
    ]
    actions = [
        ("Hide the logo", "toggle_logo", {"visible": False}, 2.2),
        ("Show the logo again", "toggle_logo", {"visible": True}, 2.2),
        ("Hide the center information", "toggle_center", {"visible": False}, 2.2),
        ("Show the center information again", "toggle_center", {"visible": True}, 2.2),
        ("Hide the clock", "toggle_time", {"visible": False}, 2.2),
        ("Show the clock again", "toggle_time", {"visible": True}, 2.8),
        ("Hide the aircraft tag", "toggle_tag", {"visible": False}, 2.2),
        ("Show the aircraft tag again", "toggle_tag", {"visible": True}, 2.8),
    ]
    while True:
        state = wait_for_director()
        should_exit, first_seen = all_windows_closed_since(state, first_seen)
        if should_exit:
            print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
            return
        # Post several ordinary messages every cycle; viewer alerts are intentionally occasional.
        for user, message in chat_messages:
            state = wait_for_director()
            should_exit, first_seen = all_windows_closed_since(state, first_seen)
            if should_exit:
                print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
                return
            dispatch(f"New live chat from {user}", "chat", {"user": user, "text": message}, 2.2)
        for label, action, payload, delay in actions:
            state = wait_for_director()
            should_exit, first_seen = all_windows_closed_since(state, first_seen)
            if should_exit:
                print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
                return
            dispatch(label, action, payload, delay)
        cycle += 1
        if cycle % 4 == 0:
            state = wait_for_director()
            if all_windows_closed_since(state, first_seen)[0]:
                print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
                return
            dispatch("A viewer sends an occasional $50 SuperChat", "superchat", {"user": "CaliPlanes", "text": "Incredible approach. Keep it up!", "amount": "$50.00"}, 4)
        if cycle % 6 == 0:
            state = wait_for_director()
            if all_windows_closed_since(state, first_seen)[0]:
                print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
                return
            dispatch("A viewer subscribes", "subscription", {"user": "JetStreamJess", "text": "Just subscribed to TerminalVector!"}, 3)
        if cycle % 8 == 0:
            state = wait_for_director()
            if all_windows_closed_since(state, first_seen)[0]:
                print("[TerminalVector demo] Both display windows are closed; stopping the show.", flush=True)
                return
            dispatch("A viewer makes an occasional donation", "donation", {"user": "CloudNine", "text": "Coffee is on me. Thanks for the coverage!", "amount": "$10.00"}, 3)
        print(f"[TerminalVector demo] Show cycle {cycle} complete; continuing.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise SystemExit(f"TerminalVector backend connection ended: {exc}")
