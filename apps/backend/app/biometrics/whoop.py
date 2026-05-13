"""Integration wrapper around the Whoop OAuth + v2 Developer API: token exchange/refresh and typed accessors for cycles, recovery, sleep, and workouts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

WHOOP_AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer"

def _raise_with_body(resp):
    """Log and raise ``HTTPStatusError`` for non-2xx Whoop responses, embedding the response body."""
    if resp.is_success:
        return
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    log.warning(
        "whoop_api_error",
        extra={"status": resp.status_code, "url": str(resp.url), "body": body},
    )
    raise httpx.HTTPStatusError(
        f"Whoop API {resp.status_code} for {resp.url}: {body}",
        request=resp.request,
        response=resp,
    )

@dataclass(slots=True)
class WhoopTokenSet:
    """Token bundle returned by the Whoop OAuth endpoint."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scope: str
    account_email: str | None = None
    user_id: str | None = None  # Whoop's own user id, useful for webhooks later

def build_authorize_url(state):
    """Build the Whoop OAuth ``/authorize`` URL for the configured client and scopes."""
    s = get_settings()
    if not s.whoop_client_id:
        raise RuntimeError("WHOOP_CLIENT_ID is not configured")
    params = {
        "client_id": s.whoop_client_id,
        "redirect_uri": s.whoop_redirect_uri,
        "response_type": "code",
        "scope": " ".join(s.whoop_scopes_list),
        "state": state,
    }
    return f"{WHOOP_AUTHORIZE_URL}?{urlencode(params)}"

def _token_set_from_response(data):
    """Convert a Whoop token JSON payload into a ``WhoopTokenSet`` with an absolute expiry."""
    expires_in = int(data.get("expires_in", 3600))
    return WhoopTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        scope=data.get("scope", ""),
    )

async def exchange_code(code):
    """Trade an OAuth ``code`` for a token set and best-effort enrich it with the user's profile."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": s.whoop_client_id,
                "client_secret": s.whoop_client_secret,
                "redirect_uri": s.whoop_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_with_body(resp)
        token = _token_set_from_response(resp.json())
        try:
            prof = await client.get(
                f"{WHOOP_API_BASE}/v2/user/profile/basic",
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
            if prof.is_success:
                p = prof.json()
                token.account_email = p.get("email") or token.account_email
                if "user_id" in p:
                    token.user_id = str(p["user_id"])
        except Exception as exc:
            log.info("whoop profile fetch failed (ok): %s", exc)
    return token

async def refresh_access_token(refresh_token):
    """Exchange a refresh token for a fresh Whoop access token."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": s.whoop_client_id,
                "client_secret": s.whoop_client_secret,
                "scope": " ".join(s.whoop_scopes_list),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_with_body(resp)
        return _token_set_from_response(resp.json())

@dataclass(slots=True)
class WhoopRecovery:
    """Typed view of one Whoop ``/recovery`` record."""

    cycle_id: str
    sleep_id: str | None
    score: int | None  # 0-100 recovery_score
    hrv_rmssd_milli: float | None
    resting_heart_rate: int | None
    score_state: str | None  # SCORED / PENDING_SCORE / UNSCORABLE
    created_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class WhoopSleep:
    """Typed view of one Whoop ``/activity/sleep`` record."""

    sleep_id: str
    start: datetime
    end: datetime
    nap: bool
    score_state: str | None
    sleep_performance: float | None  # 0-100 percentage
    sleep_efficiency: float | None
    total_in_bed_minutes: float | None
    total_asleep_minutes: float | None
    raw: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class WhoopWorkout:
    """Typed view of one Whoop ``/activity/workout`` record."""

    workout_id: str
    start: datetime
    end: datetime
    sport_id: int | None
    score_state: str | None
    strain: float | None
    average_heart_rate: int | None
    max_heart_rate: int | None
    kilojoule: float | None
    sport_name: str | None = None  # V2 returns this directly; preferred over sport_id mapping.
    zone_duration_milli: dict[str, int] = field(default_factory=dict)  # zone_zero_milli...
    raw: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class WhoopCycle:
    """Typed view of one Whoop ``/cycle`` record."""

    cycle_id: str
    start: datetime
    end: datetime | None
    score_state: str | None
    strain: float | None
    average_heart_rate: int | None
    max_heart_rate: int | None
    kilojoule: float | None
    raw: dict[str, Any] = field(default_factory=dict)

def _parse_iso(s):
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

def _required_iso(s):
    dt = _parse_iso(s)
    if dt is None:
        raise ValueError(f"unparsable Whoop datetime: {s!r}")
    return dt

class WhoopClient:
    """Thin async client over Whoop's v2 Developer API, handling pagination and auth headers."""

    def __init__(self, access_token):
        self._token = access_token

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    async def _paginated(
        self, path, *, start, end
    ):
        """Walk every ``nextToken`` page for a Whoop list endpoint and return the merged records."""
        params = {"limit": 25}
        if start:
            params["start"] = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if end:
            params["end"] = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        url = f"{WHOOP_API_BASE}/{path.lstrip('/')}"
        records = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            next_token = None
            while True:
                p = dict(params)
                if next_token:
                    p["nextToken"] = next_token
                resp = await client.get(url, headers=self._headers, params=p)
                _raise_with_body(resp)
                data = resp.json()
                records.extend(data.get("records") or [])
                next_token = data.get("next_token") or None
                if not next_token:
                    break
        return records

    async def list_recovery(
        self, *, start = None, end = None
    ):
        """Return ``WhoopRecovery`` rows in the optional ``[start, end]`` window."""
        rows = await self._paginated("v2/recovery", start=start, end=end)
        out = []
        for r in rows:
            score = r.get("score") or {}
            out.append(
                WhoopRecovery(
                    cycle_id=str(r.get("cycle_id")),
                    sleep_id=str(r["sleep_id"]) if r.get("sleep_id") else None,
                    score=score.get("recovery_score"),
                    hrv_rmssd_milli=score.get("hrv_rmssd_milli"),
                    resting_heart_rate=score.get("resting_heart_rate"),
                    score_state=r.get("score_state"),
                    created_at=_parse_iso(r.get("created_at")) or datetime.now(timezone.utc),
                    raw=r,
                )
            )
        return out

    async def list_sleep(
        self, *, start = None, end = None
    ):
        """Return ``WhoopSleep`` rows in the optional ``[start, end]`` window, with stage totals collapsed into minutes."""
        rows = await self._paginated("v2/activity/sleep", start=start, end=end)
        out = []
        for r in rows:
            score = r.get("score") or {}
            stage = (score.get("stage_summary") or {})
            in_bed = stage.get("total_in_bed_time_milli")
            asleep = stage.get("total_light_sleep_time_milli", 0) + stage.get(
                "total_slow_wave_sleep_time_milli", 0
            ) + stage.get("total_rem_sleep_time_milli", 0)
            out.append(
                WhoopSleep(
                    sleep_id=str(r.get("id") or r.get("sleep_id")),
                    start=_required_iso(r["start"]),
                    end=_required_iso(r["end"]),
                    nap=bool(r.get("nap")),
                    score_state=r.get("score_state"),
                    sleep_performance=score.get("sleep_performance_percentage"),
                    sleep_efficiency=score.get("sleep_efficiency_percentage"),
                    total_in_bed_minutes=(in_bed / 60_000.0) if in_bed else None,
                    total_asleep_minutes=(asleep / 60_000.0) if asleep else None,
                    raw=r,
                )
            )
        return out

    async def list_workouts(
        self, *, start = None, end = None
    ):
        """Return ``WhoopWorkout`` rows in the optional ``[start, end]`` window, including per-zone durations."""
        rows = await self._paginated("v2/activity/workout", start=start, end=end)
        out = []
        for r in rows:
            score = r.get("score") or {}
            zones = score.get("zone_durations") or score.get("zone_duration") or {}
            out.append(
                WhoopWorkout(
                    workout_id=str(r.get("id") or r.get("workout_id")),
                    start=_required_iso(r["start"]),
                    end=_required_iso(r["end"]),
                    sport_id=r.get("sport_id"),
                    sport_name=r.get("sport_name"),
                    score_state=r.get("score_state"),
                    strain=score.get("strain"),
                    average_heart_rate=score.get("average_heart_rate"),
                    max_heart_rate=score.get("max_heart_rate"),
                    kilojoule=score.get("kilojoule"),
                    zone_duration_milli={k: int(v) for k, v in zones.items() if v is not None},
                    raw=r,
                )
            )
        return out

    async def list_cycles(
        self, *, start = None, end = None
    ):
        """Return ``WhoopCycle`` rows in the optional ``[start, end]`` window."""
        rows = await self._paginated("v2/cycle", start=start, end=end)
        out = []
        for r in rows:
            score = r.get("score") or {}
            out.append(
                WhoopCycle(
                    cycle_id=str(r.get("id") or r.get("cycle_id")),
                    start=_required_iso(r["start"]),
                    end=_parse_iso(r.get("end")),
                    score_state=r.get("score_state"),
                    strain=score.get("strain"),
                    average_heart_rate=score.get("average_heart_rate"),
                    max_heart_rate=score.get("max_heart_rate"),
                    kilojoule=score.get("kilojoule"),
                    raw=r,
                )
            )
        return out

    async def get_user_profile(self):
        """Return the basic profile (email, user_id, names) for the authenticated Whoop user."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{WHOOP_API_BASE}/v2/user/profile/basic", headers=self._headers
            )
            _raise_with_body(resp)
            return resp.json()

WHOOP_SPORT_NAMES: dict[int, str] = {
    -1: "activity",
    0: "running",
    1: "cycling",
    16: "baseball",
    17: "basketball",
    18: "rowing",
    19: "fencing",
    20: "field hockey",
    21: "football",
    22: "golf",
    24: "ice hockey",
    25: "lacrosse",
    27: "rugby",
    28: "sailing",
    29: "skiing",
    30: "soccer",
    31: "softball",
    32: "squash",
    33: "swimming",
    34: "tennis",
    35: "track & field",
    36: "volleyball",
    37: "water polo",
    38: "wrestling",
    39: "boxing",
    42: "dance",
    43: "pilates",
    44: "yoga",
    45: "weightlifting",
    47: "cross country skiing",
    48: "functional fitness",
    49: "duathlon",
    51: "gymnastics",
    52: "hiking/rucking",
    53: "horseback riding",
    55: "kayaking",
    56: "martial arts",
    57: "mountain biking",
    59: "powerlifting",
    60: "rock climbing",
    61: "paddleboarding",
    62: "triathlon",
    63: "walking",
    64: "surfing",
    65: "elliptical",
    66: "stairmaster",
    70: "meditation",
    71: "other",
    73: "diving",
    74: "operations - tactical",
    75: "operations - medical",
    76: "operations - flying",
    77: "operations - water",
    82: "ultimate",
    83: "climber",
    84: "jumping rope",
    85: "australian football",
    86: "skateboarding",
    87: "coaching",
    88: "ice bath",
    89: "commuting",
    90: "gaming",
    91: "snowboarding",
    92: "motocross",
    93: "caddying",
    94: "obstacle course racing",
    95: "motor racing",
    96: "hiit",
    97: "spin",
    98: "jiu jitsu",
    99: "manual labor",
    100: "cricket",
    101: "pickleball",
    102: "inline skating",
    103: "box fitness",
    104: "spikeball",
    105: "wheelchair pushing",
    106: "paddle tennis",
    107: "barre",
    108: "stage performance",
    109: "high stress work",
    110: "parkour",
    111: "gaelic football",
    112: "hurling/camogie",
    113: "circus arts",
    121: "massage therapy",
    125: "watching sports",
    126: "assault bike",
    127: "kickboxing",
    128: "stretching",
    230: "table tennis",
    231: "badminton",
    232: "netball",
    233: "sauna",
    234: "disc golf",
    235: "yard work",
    236: "air compression",
    237: "percussive massage",
    238: "paintball",
    239: "ice skating",
    240: "handball",
}

def whoop_sport_name(sport_id):
    """Map a Whoop ``sport_id`` to its English short name, falling back to ``\"other\"``."""
    if sport_id is None:
        return "other"
    return WHOOP_SPORT_NAMES.get(sport_id, "other")
