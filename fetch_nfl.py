"""
fetch_nfl.py — NFL schedule/venue/rest days + official weekly injury report.

Source: nflverse/nflverse-data on GitHub (free, no key, public CSV releases — the
community-maintained aggregation of the NFL's own public data, refreshed continuously
in-season). Not a documented/stable API like MLB StatsAPI — treat a failure here the
same way fetch_savant.py treats Baseball Savant: skip the layer for this run, never fail
the whole scan.

Two releases used:
  games      -> full historical + current-season schedule, one row per game, with
                closing lines/scores baked in (informational only — NOT the live odds
                feed, see fetch_odds_football.py for that) plus venue/roof/rest days.
  injuries   -> the official weekly injury report, one row per player per report
                update (so a player can have several rows in one week as DNP -> Limited
                -> Full progresses through Wed/Thu/Fri) -- see injuries() below.

gametime is published in US Eastern time regardless of the stadium's own time zone
(standard NFL scheduling convention) -- start_utc below converts on that assumption.
"""
import csv, io, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UA = "football-model/1.0 (personal use)"

# nflverse team abbreviation -> the-odds-api's team-name last word (its nickname), so
# scan_nfl.py can look an abbreviation up in fetch_odds_football.py's dict (which is
# keyed by _norm(), i.e. lowercased last word of the full team name).
TEAM_NICKNAME = {
    "ARI": "cardinals", "ATL": "falcons", "BAL": "ravens", "BUF": "bills",
    "CAR": "panthers", "CHI": "bears", "CIN": "bengals", "CLE": "browns",
    "DAL": "cowboys", "DEN": "broncos", "DET": "lions", "GB": "packers",
    "HOU": "texans", "IND": "colts", "JAX": "jaguars", "KC": "chiefs",
    "LV": "raiders", "LAC": "chargers", "LA": "rams", "MIA": "dolphins",
    "MIN": "vikings", "NE": "patriots", "NO": "saints", "NYG": "giants",
    "NYJ": "jets", "PHI": "eagles", "PIT": "steelers", "SF": "49ers",
    "SEA": "seahawks", "TB": "buccaneers", "TEN": "titans", "WAS": "commanders",
}
GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
INJURIES_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{year}.csv"


def _get_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _to_start_utc(gameday, gametime):
    """'2026-09-14' + '13:00' (ET) -> ISO8601 UTC 'Z' string, matching the MLB model's
    start_utc convention. Returns None if either field is missing/unparseable (bye weeks,
    TBD games)."""
    if not gameday or not gametime:
        return None
    try:
        naive = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
        et = naive.replace(tzinfo=ZoneInfo("America/New_York"))
        return et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def season_games(year=None):
    """All rows for one season from the full games.csv (every NFL season since 1999).
    Returns list of dicts with the raw columns we care about, lightly typed."""
    year = str(year or datetime.now(timezone.utc).year)
    rows = _get_csv(GAMES_URL)
    out = []
    for row in rows:
        if row.get("season") != year:
            continue
        start_utc = _to_start_utc(row.get("gameday"), row.get("gametime"))
        out.append({
            "game_id": row.get("game_id"),
            "season": row.get("season"),
            "week": row.get("week"),
            "game_type": row.get("game_type"),
            "start_utc": start_utc,
            "away": row.get("away_team"),
            "home": row.get("home_team"),
            "away_score": _int_or_none(row.get("away_score")),
            "home_score": _int_or_none(row.get("home_score")),
            "stadium": row.get("stadium"),
            "roof": row.get("roof"),
            "away_rest": _int_or_none(row.get("away_rest")),
            "home_rest": _int_or_none(row.get("home_rest")),
            "div_game": row.get("div_game") == "1",
        })
    return out


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def current_week(games, now=None):
    """Pick the NFL week still 'live' as of now: the smallest week number whose games
    haven't all kicked off yet. Falls back to the highest week number with any games at
    all (end of season / offseason) rather than raising, so a caller can decide there's
    simply nothing to scan."""
    now = now or datetime.now(timezone.utc)
    by_week = {}
    for g in games:
        if g["week"] is None or g["start_utc"] is None:
            continue
        by_week.setdefault(g["week"], []).append(g)
    if not by_week:
        return None
    for week in sorted(by_week, key=lambda w: int(w)):
        starts = [datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")) for g in by_week[week]]
        if max(starts) >= now:
            return week
    return max(by_week, key=lambda w: int(w))


def week_games(season=None, week=None, now=None):
    """This week's (or a specified week's) games, with venue/roof/rest -- the football
    analogue of fetch_mlb.py's todays_games()."""
    games = season_games(season)
    week = week or current_week(games, now)
    if week is None:
        return []
    return [g for g in games if g["week"] == week]


def injuries(season=None, week=None):
    """Official weekly injury report, latest status per player plus the practice-status
    trend across the week (RULES_FOOTBALL.md category A: the trend matters more than any
    single day's tag). Returns {team_abbr: {player_full_name: {status, practice_trend,
    injury, position}}}."""
    year = str(season or datetime.now(timezone.utc).year)
    rows = _get_csv(INJURIES_URL.format(year=year))
    if week is not None:
        rows = [r for r in rows if r.get("week") == str(week)]
    by_player = {}
    for r in rows:
        key = (r.get("team"), r.get("gsis_id") or r.get("full_name"))
        by_player.setdefault(key, []).append(r)

    out = {}
    for (team, _pid), player_rows in by_player.items():
        player_rows.sort(key=lambda r: r.get("date_modified") or "")
        latest = player_rows[-1]
        trend = " → ".join(dict.fromkeys(
            r["practice_status"] for r in player_rows if r.get("practice_status")))
        out.setdefault(team, {})[latest.get("full_name", "")] = {
            "status": latest.get("report_status"),
            "practice_trend": trend or None,
            "injury": latest.get("report_primary_injury"),
            "position": latest.get("position"),
        }
    return out


def team_power_ratings(season=None, through_week=None):
    """Crude power rating: each team's average scoring margin across this season's
    COMPLETED games so far. Not opponent-adjusted (no SOS weighting) -- a much simpler
    proxy than CFB's SP+ (see fetch_cfb.team_ratings), used only as model_football.py's
    category D (mismatch) input for NFL. Returns {team_abbr: avg_margin}; a team with no
    completed games yet (season-opening week) is simply absent, not zero -- callers
    treat a missing team the same as None (model_football.py's cat_mismatch already
    no-ops when either side's rating is None)."""
    games = season_games(season)
    margins = {}
    for g in games:
        if through_week is not None and int(g["week"] or 0) > int(through_week):
            continue
        hs, aws = g["home_score"], g["away_score"]
        if hs is None or aws is None:
            continue
        margins.setdefault(g["home"], []).append(hs - aws)
        margins.setdefault(g["away"], []).append(aws - hs)
    return {team: round(sum(m) / len(m), 2) for team, m in margins.items() if m}


if __name__ == "__main__":
    games = week_games()
    print(f"{len(games)} games this week")
    for g in games:
        print(f"  {g['start_utc']}  {g['away']} @ {g['home']}  ({g['stadium']}, {g['roof']})")
    try:
        inj = injuries(week=games[0]["week"] if games else None)
        n = sum(len(v) for v in inj.values())
        print(f"\n{n} injury-report entries across {len(inj)} teams")
    except Exception as e:
        print(f"injuries() failed (non-fatal, callers should skip this layer): {e}")
