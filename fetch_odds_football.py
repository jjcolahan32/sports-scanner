"""
fetch_odds_football.py — consensus spreads/totals/moneylines for NFL and CFB.
Source: The Odds API free tier (same ODDS_API_KEY already used by the MLB model's
fetch_odds.py -- one key, multiple sports).

Same "list of entries per team pair, disambiguate by kickoff time" shape as
fetch_odds.py -- football has the doubleheader-collision risk MLB does not, but CFB
absolutely can have the same two schools' names collide with an unrelated same-week
listing artifact, and a naive last-write-wins dict is exactly the bug fetch_odds.py's
docstring already found once for MLB. Callers must use closest(), never index the dict
directly.

NFL/CFB team-name matching note: this module's dict is keyed by the LAST WORD of The
Odds API's own team name (its mascot, e.g. "Chiefs", "Buckeyes") -- fine on its own, but
CFBD's team field is the school name ONLY ("Kansas City" has no mascot in CFBD; CFB
schools are "Ohio State", not "Ohio State Buckeyes"). match_cfb_school() below bridges
that gap for scan_cfb.py: a school name that's a CASE-INSENSITIVE SUBSTRING of one (and
only one) of this module's odds entries is a safe match; ties or no match => skip the
game rather than guess (same "never guess on ambiguity" rule fetch_odds.py's own
dynamic_match()/scan.py already use for pitcher-name disambiguation).
"""
import os, json, urllib.request, urllib.parse
from datetime import datetime

BASE = "https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
SPORT_KEYS = {"nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}


def _norm(name):
    return name.lower().split()[-1]


def closest(entries, target_start_utc):
    """Pick the entry whose commence_time is nearest target_start_utc."""
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    try:
        target = datetime.fromisoformat(target_start_utc.replace("Z", "+00:00"))
    except Exception:
        return entries[0]

    def diff(e):
        try:
            t = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            return abs((t - target).total_seconds())
        except Exception:
            return float("inf")
    return min(entries, key=diff)


def match_cfb_school(school, odds_by_key):
    """Bridge CFBD's school-only name ('Ohio State') to this module's mascot-keyed odds
    dict. Returns the matching (away_norm, home_norm) key, or None if zero or 2+ team
    names in the odds set contain `school` as a substring -- ambiguous, never guessed."""
    needle = (school or "").strip().lower()
    if not needle:
        return None
    hits = {k for k, entries in odds_by_key.items()
            for e in entries
            if needle in (e.get("home", "") + " " + e.get("away", "")).lower()}
    return hits.pop() if len(hits) == 1 else None


def football_odds(sport, api_key=None):
    """h2h/spreads/totals in one call for 'nfl' or 'cfb'. Returns dict keyed by
    (away_norm, home_norm) -> list of entries, each:
      home, away, commence_time,
      home_ml, away_ml,
      home_spread, home_spread_price, away_spread, away_spread_price,
      total_point, over_price, under_price
    Any field the books haven't posted yet (early week, thin CFB market) is None --
    callers must treat a None field as "no signal", not zero."""
    sport_key = SPORT_KEYS.get(sport)
    if not sport_key:
        raise ValueError(f"unknown sport {sport!r}, expected one of {list(SPORT_KEYS)}")
    api_key = api_key or os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (free at the-odds-api.com)")
    q = urllib.parse.urlencode({"apiKey": api_key, "regions": "us",
                                "markets": "h2h,spreads,totals", "oddsFormat": "american"})
    req = urllib.request.Request(f"{BASE.format(sport_key=sport_key)}?{q}",
                                  headers={"User-Agent": "football-model/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        events = json.loads(r.read().decode())

    out = {}
    for ev in events:
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        entry = {"home": home, "away": away, "commence_time": ev.get("commence_time"),
                  "home_ml": None, "away_ml": None,
                  "home_spread": None, "home_spread_price": None,
                  "away_spread": None, "away_spread_price": None,
                  "total_point": None, "over_price": None, "under_price": None}
        for bk in ev.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}
            if "h2h" in markets and entry["home_ml"] is None:
                for oc in markets["h2h"]["outcomes"]:
                    if oc["name"] == home:
                        entry["home_ml"] = oc["price"]
                    elif oc["name"] == away:
                        entry["away_ml"] = oc["price"]
            if "spreads" in markets and entry["home_spread"] is None:
                for oc in markets["spreads"]["outcomes"]:
                    if oc["name"] == home:
                        entry["home_spread"], entry["home_spread_price"] = oc.get("point"), oc["price"]
                    elif oc["name"] == away:
                        entry["away_spread"], entry["away_spread_price"] = oc.get("point"), oc["price"]
            if "totals" in markets and entry["total_point"] is None:
                for oc in markets["totals"]["outcomes"]:
                    if oc["name"] == "Over":
                        entry["total_point"], entry["over_price"] = oc.get("point"), oc["price"]
                    elif oc["name"] == "Under":
                        entry["under_price"] = oc["price"]
            if all(entry[k] is not None for k in ("home_ml", "home_spread", "total_point")):
                break
        key = (_norm(away), _norm(home))
        out.setdefault(key, []).append(entry)
    return out


if __name__ == "__main__":
    for sport in ("nfl", "cfb"):
        try:
            odds = football_odds(sport)
        except Exception as e:
            print(f"{sport}: fetch failed -- {e}")
            continue
        n = sum(len(v) for v in odds.values())
        print(f"{sport}: {n} game(s) across {len(odds)} team pair(s)")
        for entries in list(odds.values())[:3]:
            e = entries[0]
            print(f"  {e['away']} ({e['away_ml']}) @ {e['home']} ({e['home_ml']})  "
                  f"spread {e['home_spread']}  total {e['total_point']}  -- {e['commence_time']}")
