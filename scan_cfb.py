"""
scan_cfb.py — the unattended CFB job. Runs on the per-game-day schedule described in
RULES_FOOTBALL.md Section 6 (see .github/workflows/scan_cfb.yml).

Unlike scan_nfl.py (one scan covers the whole week, since NFL plays almost entirely on
Sunday/Monday/Thursday), CFB slates land Tue-Sat -- each day's games get graded on THAT
day only (in_window() below restricts to today's ET calendar date, not "anything not
kicked off yet"), so Tuesday's scan never fires early on Saturday's 50-game slate using a
week-stale read. Saturday itself gets its own morning lock given the doc's explicit "2+
stack matters more here to avoid overextending across 40+ games" caution.

No official CFB injury report exists (see fetch_cfb.py's docstring and
RULES_FOOTBALL.md Section 7) -- category A here only fires off an optional
hand-maintained public_cfb_injuries.json; most games will simply have no injury signal,
which is honest, not a bug.
"""
import os, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import fetch_cfb, fetch_weather, fetch_odds_football, model_football, notify, rlm
from model import american_to_stake, cap_rule  # pure odds math, reused unmodified

STATE_FILE = os.environ.get("STATE_CFB_FILE", "state_cfb.json")
OPENS_FILE = os.environ.get("OPENS_CFB_FILE", "opens_cfb.json")
LAST_RUN_FILE = os.environ.get("LAST_SCAN_CFB_FILE", "last_scan_cfb.json")
NTFY_TOPIC_FOOTBALL = os.environ.get("NTFY_TOPIC_FOOTBALL", "")

# Weekday numbers use datetime.weekday(): Mon=0 ... Sun=6. See RULES_FOOTBALL.md Section 6.
SCAN_CHECKPOINTS_ET = [
    (1, 10, 0),   # Tue 10:00 -- standalone Tue games, own same-day scan
    (2, 10, 0),   # Wed 10:00 -- standalone Wed games
    (3, 14, 0),   # Thu 14:00 -- Thu games mini-scan
    (4, 16, 0),   # Fri 16:00 -- Fri games mini-scan
    (5, 9, 0),    # Sat 09:00 -- lock the main Saturday slate
]
CHECKPOINT_GRACE_MINUTES = 30


def _et_now(now_utc):
    return now_utc.astimezone(ZoneInfo("America/New_York"))


def _checkpoint_label(weekday, hh, mm):
    return f"{weekday}-{hh:02d}:{mm:02d}"


def _due_checkpoints(et, fired):
    now_minutes = et.hour * 60 + et.minute
    due = []
    for wd, hh, mm in SCAN_CHECKPOINTS_ET:
        if et.weekday() != wd:
            continue
        label = _checkpoint_label(wd, hh, mm)
        if label in fired:
            continue
        if 0 <= now_minutes - (hh * 60 + mm) <= CHECKPOINT_GRACE_MINUTES:
            due.append(label)
    return due


def market_hours_open(now_utc=None):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    now_utc = now_utc or datetime.now(timezone.utc)
    et = _et_now(now_utc)
    today = et.strftime("%Y-%m-%d")
    state = load_json(LAST_RUN_FILE, {})
    fired = set(state.get("fired", [])) if state.get("date") == today else set()
    return bool(_due_checkpoints(et, fired))


def record_run(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    et = _et_now(now_utc)
    today = et.strftime("%Y-%m-%d")
    state = load_json(LAST_RUN_FILE, {})
    fired = set(state.get("fired", [])) if state.get("date") == today else set()
    fired.update(_due_checkpoints(et, fired))
    save_json(LAST_RUN_FILE, {"date": today, "fired": sorted(fired)})


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def in_window(game, now=None):
    """Hasn't kicked off yet AND kicks off on today's ET calendar date -- each day's
    slate gets graded on its own day, see module docstring."""
    if not game.get("start_utc"):
        return False
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(game["start_utc"].replace("Z", "+00:00"))
    if start <= now:
        return False
    return start.astimezone(ZoneInfo("America/New_York")).date() == _et_now(now).date()


def _team_home_venue_id(team, all_season_games):
    """A team's own typical home venue -- looked up from any OTHER game this season
    where they played at home, so cat_dome_travel_total can tell whether a traveling
    team is normally a dome team. Best-effort: returns None if the team hasn't hosted
    yet this season (early-season edge case), which just means that signal doesn't fire."""
    for g in all_season_games:
        if g["home"] == team and g.get("venue_id") is not None:
            return g["venue_id"]
    return None


def build_candidate(game, injuries_by_team, ratings, league_avg, venue_cache, all_season_games):
    home, away = game["home"], game["away"]
    venue = venue_cache.get(game.get("venue_id"), {})
    roof = "dome" if venue.get("dome") else "outdoor"

    away_home_vid = _team_home_venue_id(away, all_season_games)
    away_team_is_dome_team = bool(venue_cache.get(away_home_vid, {}).get("dome")) if away_home_vid else False

    wind_mph = temp_f = precip = None
    if roof == "outdoor" and venue.get("lat") is not None and game.get("start_utc"):
        try:
            when = datetime.fromisoformat(game["start_utc"].replace("Z", "+00:00"))
            fc = fetch_weather.forecast_at(venue["lat"], venue["lon"], when)
        except Exception as e:
            print(f"weather fetch failed for {away}@{home} (non-fatal, skipping weather this run): {e}")
            fc = None
        if fc:
            wind_mph, temp_f = fc.get("wind_mph"), fc.get("temp_f")
            precip = bool(fc.get("short") and any(w in fc["short"].lower() for w in ("rain", "snow", "storm", "shower")))

    home_r, away_r = ratings.get(home, {}), ratings.get(away, {})
    return {
        "sport": "cfb", "home": home, "away": away,
        "home_rating": home_r.get("rating"), "away_rating": away_r.get("rating"),
        "league_avg_rating": league_avg,
        "home_injury_burden": model_football.injury_burden(injuries_by_team.get(home)) if injuries_by_team else None,
        "away_injury_burden": model_football.injury_burden(injuries_by_team.get(away)) if injuries_by_team else None,
        "home_rest": None, "away_rest": None,  # CFBD doesn't publish a rest-days field like nflverse's games.csv
        "div_game": (home_r.get("conference") and home_r.get("conference") == away_r.get("conference")),
        "roof": roof,
        "away_team_is_dome_team": away_team_is_dome_team,
        "wind_mph": wind_mph, "temp_f": temp_f, "precip": precip,
    }


def _entry_for(game, odds):
    """Match a CFBD game (school-only names) to an odds entry (mascot-suffixed full
    names) via fetch_odds_football.match_cfb_school() -- try the home school first,
    fall back to the away school if the home name alone was ambiguous (e.g. a short
    school name that's a substring of several full names)."""
    key = (fetch_odds_football.match_cfb_school(game["home"], odds)
           or fetch_odds_football.match_cfb_school(game["away"], odds))
    if key is None:
        return {}
    return fetch_odds_football.closest(odds.get(key, []), game["start_utc"]) or {}


def _price_for(market, side, entry):
    if market == "ml":
        return (entry.get("home_ml") if side == "home" else entry.get("away_ml")), None
    if market == "spread":
        if side == "home":
            return entry.get("home_spread_price"), entry.get("home_spread")
        return entry.get("away_spread_price"), entry.get("away_spread")
    if market == "total":
        if side == "over":
            return entry.get("over_price"), entry.get("total_point")
        return entry.get("under_price"), entry.get("total_point")
    return None, None


def record_opens(games, odds, opens, today_key):
    if opens.get("day") != today_key:
        opens = {"day": today_key, "lines": {}}
    lines = opens["lines"]
    for g in games:
        entry = _entry_for(g, odds)
        if not entry:
            continue
        lines.setdefault(str(g["game_id"]), {
            "home_ml": entry.get("home_ml"), "away_ml": entry.get("away_ml"),
            "home_spread_price": entry.get("home_spread_price"), "away_spread_price": entry.get("away_spread_price"),
            "over_price": entry.get("over_price"), "under_price": entry.get("under_price"),
        })
    return opens


def _open_price(opens, game_id, market, side):
    o = opens.get("lines", {}).get(str(game_id), {})
    if market == "ml":
        return o.get("home_ml") if side == "home" else o.get("away_ml")
    if market == "spread":
        return o.get("home_spread_price") if side == "home" else o.get("away_spread_price")
    if market == "total":
        return o.get("over_price") if side == "over" else o.get("under_price")
    return None


def grade_game(game, candidate, odds, opens):
    entry = _entry_for(game, odds)
    results = []
    for market, grader in (("spread", model_football.grade_spread),
                            ("total", model_football.grade_total),
                            ("ml", model_football.grade_ml)):
        g = grader(candidate)
        if g["side"] is None:
            results.append({**g, "game": game})
            continue
        price, point = _price_for(market, g["side"], entry)
        if price is None:
            # A real 2+-category CONFIRMED edge with no live price yet still can't be
            # staked or notified -- downgrade to NOTE so main()'s notify/stake code
            # never sees a "CONFIRMED" row missing risk/to_win. Re-evaluated fresh next
            # scan once a book actually posts this side.
            if g["verdict"] == "CONFIRMED":
                g["verdict"] = "NOTE"
            g["reason"] += " (no live price posted yet)"
            results.append({**g, "game": game})
            continue
        open_price = _open_price(opens, game["game_id"], market, g["side"])
        sig = rlm.evaluate(open_price, price) if open_price is not None else {"tag": "NEUTRAL", "detail": ""}
        new_verdict, note = model_football.verdict_adjust_football(g["verdict"], sig["tag"])
        g["verdict"], g["rlm"], g["rlm_note"] = new_verdict, sig, note
        g["price"], g["point"] = price, point
        if new_verdict == "CONFIRMED":
            risk, win = american_to_stake(price)
            g["risk"], g["to_win"], g["cap"] = risk, win, cap_rule(price)
        results.append({**g, "game": game})
    return results


def _selection_label(market, g):
    game = g["game"]
    if market == "ml":
        team = game["home"] if g["side"] == "home" else game["away"]
        return f"{team} ML"
    if market == "spread":
        team = game["home"] if g["side"] == "home" else game["away"]
        pt = g.get("point")
        return f"{team} {pt:+.1f}" if pt is not None else f"{team} spread"
    label = "Over" if g["side"] == "over" else "Under"
    pt = g.get("point")
    return f"{label} {pt}" if pt is not None else label


def main():
    if not market_hours_open():
        print("Not within grace of a CFB scan checkpoint — skipping, no API calls made.")
        return
    record_run()

    now = datetime.now(timezone.utc)
    today_key = _et_now(now).strftime("%Y-%m-%d")

    try:
        all_season_games = fetch_cfb.season_games()
    except Exception as e:
        print(f"CFBD schedule fetch failed, skipping this run: {e}")
        return
    games = [g for g in all_season_games if in_window(g, now)]
    if not games:
        print("No CFB games kicking off today.")
        return

    try:
        odds = fetch_odds_football.football_odds("cfb")
    except Exception as e:
        print(f"Odds fetch failed, skipping this run: {e}")
        return

    opens = record_opens(games, odds, load_json(OPENS_FILE, {}), today_key)
    save_json(OPENS_FILE, opens)

    injuries_by_team = fetch_cfb.public_cfb_injuries()  # optional, hand-maintained -- see RULES_FOOTBALL.md 2A/7

    try:
        ratings = fetch_cfb.team_ratings()
    except Exception as e:
        print(f"SP+ ratings fetch failed, skipping mismatch signal this run: {e}")
        ratings = {}
    rating_vals = [r["rating"] for r in ratings.values() if r.get("rating") is not None]
    league_avg = sum(rating_vals) / len(rating_vals) if rating_vals else 0.0

    try:
        venue_cache = fetch_cfb.venues()
    except Exception as e:
        print(f"Venue fetch failed, skipping weather signal this run: {e}")
        venue_cache = {}

    state = load_json(STATE_FILE, {})
    sent = set(state.get("sent", [])) if state.get("date") == today_key else set()

    all_results = []
    for game in games:
        candidate = build_candidate(game, injuries_by_team, ratings, league_avg, venue_cache, all_season_games)
        all_results.extend(grade_game(game, candidate, odds, opens))

    fresh, ntfy_lines = [], []
    for market_result in all_results:
        game, market = market_result["game"], market_result["market"]
        key = f"{game['game_id']}:{market}"
        if market_result["verdict"] not in ("CONFIRMED", "LEAN") or key in sent:
            continue
        sel = _selection_label(market, market_result)
        stake = (f"risk {market_result['risk']}u/win {market_result['to_win']}u"
                 if market_result["verdict"] == "CONFIRMED" else "informational — not staked")
        price_str = f"{market_result['price']:+d}" if market_result.get("price") is not None else ""
        when = datetime.fromisoformat(game["start_utc"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")).strftime("%a %-m/%-d %-I:%M %p ET")
        title_line = (f"[CFB] {game['away']} @ {game['home']} — {market.upper()}  "
                      f"{market_result['verdict']}\n{sel} {price_str} ({stake}) — {when}")
        reason_line = market_result["reason"] + (f"  [{market_result['rlm']['tag']}]" if market_result.get("rlm") else "")
        ntfy_lines.append(f"{title_line}\n{reason_line}")
        sent.add(key)
        fresh.append((game, market, market_result))

    log_card(all_results, today_key)

    if not fresh:
        print("No new qualifying CFB plays this scan.")
        return

    body = "\n\n".join(ntfy_lines)
    title = f"🏈 {len(fresh)} CFB play(s) — {today_key}"
    if NTFY_TOPIC_FOOTBALL:
        notify.push(title, body, topic=NTFY_TOPIC_FOOTBALL, tag="football")
    else:
        print("NTFY_TOPIC_FOOTBALL not set — skipping ntfy push (picks are still logged to the card file).")

    save_json(STATE_FILE, {"date": today_key, "sent": sorted(sent)})
    print("Notified:\n" + body)


def log_card(all_results, today_key):
    path = f"card_cfb_{today_key}.json"
    card = load_json(path, {"date": today_key, "plays": []})
    seen = {(p["game_id"], p["market"]) for p in card["plays"]}
    for r in all_results:
        game = r["game"]
        k = (game["game_id"], r["market"])
        if k in seen or r["side"] is None:
            continue
        card["plays"].append({
            "game_id": game["game_id"], "start_utc": game["start_utc"],
            "home": game["home"], "away": game["away"], "market": r["market"],
            "side": r["side"], "selection": _selection_label(r["market"], r),
            "price": r.get("price"), "point": r.get("point"),
            "risk": r.get("risk"), "to_win": r.get("to_win"), "cap": r.get("cap"),
            "verdict": r["verdict"], "rlm_tag": (r.get("rlm") or {}).get("tag", "NEUTRAL"),
            "graded": False, "result": None,
        })
        seen.add(k)
    save_json(path, card)


if __name__ == "__main__":
    main()
