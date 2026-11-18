"""Extract 2026 F1 session data from the OpenF1 API.

Stage 1, step 2: request the data and count rows.
Saving the raw data to disk comes in step 3.
"""
import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.openf1.org/v1"
SEASON = 2026

# OpenF1 free tier allows 30 requests/minute: one request every 2.1 s stays under it.
PAUSE_SECONDS = 2.1
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4  # 1 try + 3 retries, waiting 2, 4 and 8 s
RETRYABLE_STATUS = {429, 500, 502, 503, 504}  # too many requests or server errors: worth retrying

# Sessions we ingest and the endpoints requested for each one.
# The starting grid hangs from the qualifying session in OpenF1, not from the race.
SESSION_ENDPOINTS = {
    "Qualifying": ["drivers", "session_result", "laps", "stints", "pit", "weather", "starting_grid"],
    "Race": ["drivers", "session_result", "laps", "stints", "pit", "weather"],
}


def fetch(endpoint: str, **params) -> list[dict]:
    """GET one endpoint and return its rows as a list of dicts.

    Pauses before every request, retries temporary failures with exponential
    backoff, and turns any 404 into an empty list (see the comment below).
    """
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        time.sleep(PAUSE_SECONDS)
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as error:
            problem = f"network error: {error}"
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                # OpenF1 answers 404 "No results found" both for real empty results and for a
                # misspelled endpoint or filter, so the two cannot be told apart here.
                # Every request is logged with its row count (stage 1, step 3) and dbt tests
                # cross-check completeness against the source's own data (stage 2).
                return []
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()  # a real error (wrong endpoint, bad params): stop here
            problem = f"HTTP {response.status_code}"

        if attempt == MAX_ATTEMPTS:
            raise RuntimeError(f"{endpoint} {params} failed after {MAX_ATTEMPTS} attempts: {problem}")
        wait = 2 ** attempt  # 2, 4, 8 s
        print(f"  retry {attempt}/{MAX_ATTEMPTS - 1} for {endpoint} in {wait} s ({problem})")
        time.sleep(wait)


def finished_sessions(season: int) -> list[dict]:
    """Qualifying and race sessions of the season that already ended, oldest first."""
    now = datetime.now(timezone.utc)
    sessions = [
        s for s in fetch("sessions", year=season)
        if s["session_name"] in SESSION_ENDPOINTS
        and datetime.fromisoformat(s["date_end"]) < now  # live or future sessions are incomplete
    ]
    return sorted(sessions, key=lambda s: s["date_start"])


def extract_session(session: dict) -> dict[str, list[dict]]:
    """Request every endpoint of one session. Returns {endpoint: rows}."""
    return {
        endpoint: fetch(endpoint, session_key=session["session_key"])
        for endpoint in SESSION_ENDPOINTS[session["session_name"]]
    }


if __name__ == "__main__":
    # Step 2 smoke test: only the first finished weekend, printing row counts.
    meetings = fetch("meetings", year=SEASON)
    sessions = finished_sessions(SEASON)
    print(f"{SEASON}: {len(meetings)} meetings, {len(sessions)} finished qualifying/race sessions")

    first_meeting = sessions[0]["meeting_key"]
    for session in [s for s in sessions if s["meeting_key"] == first_meeting]:
        rows = extract_session(session)
        counts = ", ".join(f"{name}={len(r)}" for name, r in rows.items())
        print(f"{session['country_name']} {session['session_name']} ({session['session_key']}): {counts}")
