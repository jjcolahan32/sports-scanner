"""
fetch_cfb.py — CFB schedule/venues/SP+ ratings via CollegeFootballData (CFBD).

Source: api.collegefootballdata.com. Free tier, but requires a personal API key (unlike
MLB StatsAPI/nflverse) -- request one at collegefootballdata.com/key and set
CFBD_API_KEY. Bearer-token auth.

No injury function here on purpose -- CFBD has no official injury endpoint, and CFB
injury reporting itself is opaque (no league-mandated report, see RULES_FOOTBALL.md
Section 7). Confirmed absences get supplied by hand in public_cfb_injuries.json
(optional, same pattern as the MLB model's public.json) rather than an automated feed --
never guess at an unconfirmed one.

CFBD's schema has shifted field-casing across API versions before, so field lookups here
go through _field() (tries a couple of known key spellings) rather than a single hard
subscript -- keeps a schema tweak from being a hard crash, same "skip the layer, don't
kill the run" tolerance fetch_savant.py has for its own unofficial source.
"""
import os, json, urllib.request, urllib.parse
from datetime import datetime, timezone

from fetch_nfl import current_week  # generic over any {week, start_utc} game list

BASE = "https://api.collegefootballdata.com"
UA = "football-model/1.0 (personal use)"
VENUE_CACHE_FILE = os.environ.get("CFB_VENUE_CACHE_FILE", "venues_cfb_cache.json")


def _get(path, params=None):
    api_key = os.environ.get("CFBD_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set CFBD_API_KEY (free at collegefootballdata.com/key)")
    q = f"?{urllib.parse.urlencode(params)}" if params else ""
    req = urllib.request.Request(
        f"{BASE}{path}{q}",
        headers={"User-Agent": UA, "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _field(d, *names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def season_games(year=None, season_type="regular"):
    """All FBS games for a season, normalized to the same {game_id, season, week,
    start_utc, away, home, away_score, home_score, venue_id, neutral_site} shape
    fetch_nfl.py uses, so current_week() works unmodified across both sports."""
    year = int(year or datetime.now(timezone.utc).year)
    games = _get("/games", {"year": year, "seasonType": season_type})
    out = []
    for g in games:
        start = _field(g, "startDate", "start_date")
        start_utc = None
        if start:
            try:
                start_utc = (datetime.fromisoformat(start.replace("Z", "+00:00"))
                             .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                pass
        out.append({
            "game_id": _field(g, "id"),
            "season": year,
            "week": _field(g, "week"),
            "start_utc": start_utc,
            "away": _field(g, "awayTeam", "away_team"),
            "home": _field(g, "homeTeam", "home_team"),
            "away_conference": _field(g, "awayConference", "away_conference"),
            "home_conference": _field(g, "homeConference", "home_conference"),
            "away_score": _field(g, "awayPoints", "away_points"),
            "home_score": _field(g, "homePoints", "home_points"),
            "venue_id": _field(g, "venueId", "venue_id"),
            "venue": _field(g, "venue"),
            "neutral_site": bool(_field(g, "neutralSite", "neutral_site", default=False)),
            "completed": bool(_field(g, "completed", default=False)),
        })
    return out


def week_games(season=None, week=None, now=None, season_type="regular"):
    """This week's (or a specified week's) FBS games -- the CFB analogue of
    fetch_nfl.week_games()."""
    games = season_games(season, season_type)
    week = week or current_week(games, now)
    if week is None:
        return []
    return [g for g in games if g["week"] == week]


def venues(refresh=False, cache_file=None):
    """{venue_id: {name, city, state, lat, lon, dome}} for every FBS venue. Cached to
    disk -- venues almost never change, no reason to hit the API every scan. Set
    refresh=True (or delete the cache file) to force a re-pull."""
    cache_file = cache_file or VENUE_CACHE_FILE
    if not refresh:
        try:
            with open(cache_file) as f:
                return {int(k): v for k, v in json.load(f).items()}
        except FileNotFoundError:
            pass
    rows = _get("/venues")
    out = {}
    for v in rows:
        vid = _field(v, "id")
        if vid is None:
            continue
        out[vid] = {
            "name": _field(v, "name"),
            "city": _field(v, "city"),
            "state": _field(v, "state"),
            "lat": _field(v, "latitude"),
            "lon": _field(v, "longitude"),
            "dome": bool(_field(v, "dome", default=False)),
        }
    with open(cache_file, "w") as f:
        json.dump(out, f)
    return out


def team_ratings(year=None):
    """SP+ ratings (conference-adjusted by construction -- see RULES_FOOTBALL.md
    Section 2E) -> {team_name: {rating, offense, defense}}."""
    year = int(year or datetime.now(timezone.utc).year)
    rows = _get("/ratings/sp", {"year": year})
    out = {}
    for r in rows:
        team = _field(r, "team")
        if not team:
            continue
        offense = _field(r, "offense", default={}) or {}
        defense = _field(r, "defense", default={}) or {}
        out[team] = {
            "rating": _field(r, "rating"),
            "offense": _field(offense, "rating") if isinstance(offense, dict) else None,
            "defense": _field(defense, "rating") if isinstance(defense, dict) else None,
            "conference": _field(r, "conference"),
        }
    return out


def public_cfb_injuries(path=None):
    """Optional hand-maintained confirmed-absence file -- see module docstring. Missing
    file just means no manual signal this run, not an error."""
    path = path or os.environ.get("PUBLIC_CFB_INJURIES_FILE", "public_cfb_injuries.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


if __name__ == "__main__":
    games = week_games()
    print(f"{len(games)} FBS games this week")
    for g in games[:10]:
        print(f"  {g['start_utc']}  {g['away']} @ {g['home']}  (venue_id {g['venue_id']})")
    try:
        v = venues()
        print(f"\n{len(v)} venues cached")
    except Exception as e:
        print(f"venues() failed (non-fatal, callers should skip weather this run): {e}")
    try:
        ratings = team_ratings()
        print(f"{len(ratings)} SP+ ratings loaded")
    except Exception as e:
        print(f"team_ratings() failed (non-fatal): {e}")
