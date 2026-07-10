"""
Purpose: Google Calendar v3 client for per-core booking events.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22
Input: Per-core OAuth credentials at
       ``~/.wigamig/cores/<core>/google_calendar.json`` (created by
       ``murmurent core-calendar-auth`` via the InstalledAppFlow).
Output: Calendar event ID + html link that the booking endpoint
        stitches into the RequestSummary's BookingSlot.

Design (Phase 3c of the cores rollout — docs/cores_plan.md §5c):

  - Identity: the core *leader*'s calendar holds the events. Gary
    runs the one-time OAuth flow on his machine; the refresh token
    lands at ``~/.wigamig/cores/biocore/google_calendar.json`` and
    is loaded by the dashboard process.
  - Sync: the booking endpoint calls ``create_event`` inline before
    persisting the request. Failure is non-blocking — the request is
    still created, just with an empty ``calendar_event_id`` and a
    warning surfaced to the leader's inbox so they can re-attempt or
    fix the auth.
  - Lazy imports: all google-api-python-client imports happen inside
    the helper functions, so the dashboard boots cleanly even when
    the ``gcal`` extra isn't installed.

Storage layout:

  ~/.wigamig/cores/<core>/
    google_oauth_client.json     # OAuth client_id/secret from Google Cloud
                                  # (provided by the core leader once)
    google_calendar.json          # refresh token after the auth flow
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarError(RuntimeError):
    """Calendar API call failed (auth missing, libs missing, transport error)."""


@dataclass
class CalendarEvent:
    """Subset of the Google Calendar event response we care about."""

    id: str
    html_link: str
    start: str
    end: str
    summary: str = ""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _cores_dir() -> Path:
    """Per-core credential root (machine-local)."""
    return Path(
        os.environ.get("WIGAMIG_HOME") or (Path.home() / ".wigamig")
    ) / "cores"


def creds_path(core: str) -> Path:
    """Where the saved refresh token lives for ``core``."""
    return _cores_dir() / core / "google_calendar.json"


def oauth_client_path(core: str) -> Path:
    """Where the OAuth client_secret.json lives (provided by leader)."""
    return _cores_dir() / core / "google_oauth_client.json"


def is_connected(core: str) -> bool:
    """True iff a refresh-token file exists for ``core``. Cheap check —
    doesn't validate the token, just whether the file is present.
    The booking endpoint calls this before attempting a create_event so
    it can fall through silently on first run (before Gary auths)."""
    return creds_path(core).is_file()


# ---------------------------------------------------------------------------
# Auth flow (called by the CLI)
# ---------------------------------------------------------------------------

def run_oauth_flow(core: str) -> Path:
    """Run the InstalledAppFlow (opens browser) and persist the refresh
    token. Idempotent — overwrites any existing token.

    Requires ``google-auth-oauthlib`` (``pip install murmurent[gcal]``).
    Requires ``oauth_client_path(core)`` to exist (Gary downloads it
    from Google Cloud Console once when he sets up the OAuth client).
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError as exc:
        raise CalendarError(
            "google-auth-oauthlib not installed; "
            "run: pip install 'murmurent[gcal]'"
        ) from exc
    cp = oauth_client_path(core)
    if not cp.is_file():
        raise CalendarError(
            f"missing OAuth client secret at {cp}. "
            "Create an OAuth 2.0 Client ID (type=Desktop) in Google Cloud "
            "Console, download the JSON, save it to that path, then re-run."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(cp), SCOPES)
    creds = flow.run_local_server(port=0)
    out = creds_path(core)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creds.to_json(), encoding="utf-8")
    try:
        out.chmod(0o600)
    except OSError:
        pass
    return out


def _load_credentials(core: str):
    """Build a Credentials object from the saved refresh token, refreshing
    the access token if needed. Raises CalendarError on any failure."""
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
    except ImportError as exc:
        raise CalendarError(
            "google-auth not installed; run: pip install 'murmurent[gcal]'"
        ) from exc
    cp = creds_path(core)
    if not cp.is_file():
        raise CalendarError(
            f"calendar not connected for core {core!r}; "
            f"the leader must run: murmurent core-calendar-auth --core {core}"
        )
    data = json.loads(cp.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        cp.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _build_service(core: str):
    """Build a Calendar v3 service handle for ``core``. Cached by core
    name within a process to avoid repeated discovery calls."""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise CalendarError(
            "google-api-python-client not installed; "
            "run: pip install 'murmurent[gcal]'"
        ) from exc
    creds = _load_credentials(core)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Public API used by the booking endpoint
# ---------------------------------------------------------------------------

def _normalize_iso_for_google(iso: str) -> str:
    """Google Calendar's events.insert rejects ISO8601 strings without
    a seconds component (``2026-05-28T14:00-04:00`` → HTTP 400). Parse
    + reformat so the API always sees ``YYYY-MM-DDTHH:MM:SS±HH:MM``.

    Falls through unchanged if parsing fails (let Google return its
    own error rather than masking it).
    """
    import datetime as _dt
    if not iso:
        return iso
    try:
        dt = _dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.isoformat(timespec="seconds")


def create_event(
    core: str,
    *,
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
) -> CalendarEvent:
    """Create a calendar event on the core leader's calendar.

    Times must be ISO8601 with timezone offset. We normalise both
    endpoints to include a seconds component (Google's API rejects
    minute-only forms with HTTP 400). ``attendees`` is a list of
    email addresses; non-email handles are silently skipped (Google
    requires real RFC822 emails — our @netname handles aren't valid).
    """
    start_iso = _normalize_iso_for_google(start_iso)
    end_iso = _normalize_iso_for_google(end_iso)
    try:
        from googleapiclient.errors import HttpError  # type: ignore
    except ImportError as exc:
        raise CalendarError(
            "google-api-python-client not installed; "
            "run: pip install 'murmurent[gcal]'"
        ) from exc
    service = _build_service(core)
    body: dict = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    emails = [a for a in (attendees or []) if "@" in a and "." in a.split("@")[-1]]
    if emails:
        body["attendees"] = [{"email": e} for e in emails]
    try:
        event = service.events().insert(
            calendarId=calendar_id, body=body, sendUpdates="all",
        ).execute()
    except HttpError as exc:
        raise CalendarError(f"calendar insert failed: {exc}") from exc
    return CalendarEvent(
        id=str(event.get("id") or ""),
        html_link=str(event.get("htmlLink") or ""),
        start=start_iso,
        end=end_iso,
        summary=summary,
    )


def delete_event(
    core: str, event_id: str, *, calendar_id: str = "primary",
) -> None:
    """Delete a previously-created event. Safe to call on a non-existent
    event ID — Google returns 410 Gone which we swallow."""
    if not event_id:
        return
    try:
        from googleapiclient.errors import HttpError  # type: ignore
    except ImportError as exc:
        raise CalendarError(
            "google-api-python-client not installed; "
            "run: pip install 'murmurent[gcal]'"
        ) from exc
    service = _build_service(core)
    try:
        service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all",
        ).execute()
    except HttpError as exc:
        # 404/410 mean the event was already deleted out from under us.
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "resp", None), "status", None
        )
        if status in (404, 410):
            return
        raise CalendarError(f"calendar delete failed: {exc}") from exc


__all__ = [
    "SCOPES",
    "CalendarError",
    "CalendarEvent",
    "creds_path",
    "oauth_client_path",
    "is_connected",
    "run_oauth_flow",
    "create_event",
    "delete_event",
]
