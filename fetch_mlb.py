"""
fetch_mlb.py — today's MLB games, start times, and probable pitchers.
Source: public MLB StatsAPI. No login, no key.
"""
import json, urllib.request
from datetime import datetime, timezone

SCHED = ("https://statsapi.mlb.com/api/v1/schedule"
         "?sportId=1&date={date}&hydrate=probablePitcher,team,venue")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def todays_games(date=None):
    """Return list of dicts: game_pk, start_utc, home, away, venue, home_prob, away_prob."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _get(SCHED.format(date=date))
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            games.append({
                "game_pk": g.get("gamePk"),
                "start_utc": g.get("gameDate"),                       # ISO8601 Z
                "game_type": g.get("gameType"),                       # 'R','A'(allstar),'E'(exhib)...
                "venue": g.get("venue", {}).get("name", ""),
                "home": home.get("team", {}).get("name", ""),
                "away": away.get("team", {}).get("name", ""),
                "home_prob": (home.get("probablePitcher") or {}).get("fullName"),
                "away_prob": (away.get("probablePitcher") or {}).get("fullName"),
            })
    return games


RESULTS = ("https://statsapi.mlb.com/api/v1/schedule"
           "?sportId=1&date={date}&hydrate=team,linescore")


def results_for_date(date):
    """Return {game_pk: {status, home, away, home_score, away_score}} for a date."""
    data = _get(RESULTS.format(date=date))
    out = {}
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            out[g.get("gamePk")] = {
                "status": g.get("status", {}).get("abstractGameState"),   # Final / Live / Preview
                "detailed": g.get("status", {}).get("detailedState"),
                "home": home.get("team", {}).get("name", ""),
                "away": away.get("team", {}).get("name", ""),
                "home_score": home.get("score"),
                "away_score": away.get("score"),
            }
    return out


if __name__ == "__main__":
    for g in todays_games():
        print(f"{g['start_utc']}  {g['away']} @ {g['home']}  "
              f"[{g['away_prob']} vs {g['home_prob']}]  {g['venue']}")
