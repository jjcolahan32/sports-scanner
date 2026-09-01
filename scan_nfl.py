"""
scan_nfl.py — the unattended NFL job. Runs on the weekly-cycle schedule described in
RULES_FOOTBALL.md Section 6 (see .github/workflows/scan_nfl.yml).

Flow each run:
  1. Pull this NFL week's games (fetch_nfl.week_games), the official injury report,
     season power ratings, and live spreads/totals/moneylines (fetch_odds_football).
  2. Build one candidate dict per game (both teams' signals) and grade it independently
     for all three markets (model_football.grade_spread/grade_total/grade_ml).
  3. RLM overlay (rlm.py, reused unmodified) can promote a lone-category NOTE to
     CONFIRMED, or downgrade a CONFIRMED to LEAN on market conflict
     (model_football.verdict_adjust_football).
  4. Notify NEW CONFIRMED/LEAN picks only (dedupe by game_id+market in state_nfl.json)
     via ntfy, on football's own topic (NTFY_TOPIC_FOOTBALL) so picks don't mix into the
     MLB feed. Discord is intentionally not wired up for football (ntfy only, for now).

NOTE-tier verdicts (exactly one category fired) are logged to the card file for later
review but never pushed as a notification -- RULES_FOOTBALL.md's "never force a play to
fill a slate" philosophy, and 16 games/week would otherwise mean a lot of single-category
noise.
"""
import os, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import fetch_nfl, fetch_weather, fetch_odds_football, stadiums_football, model_football, notify, rlm
from model import american_to_stake, cap_rule  # pure odds math, reused unmodified

STATE_FILE = os.environ.get("STATE_NFL_FILE", "state_nfl.json")
OPENS_FILE = os.environ.get("OPENS_NFL_FILE", "opens_nfl.json")
LAST_RUN_FILE = os.environ.get("LAST_SCAN_NFL_FILE", "last_scan_nfl.json")
NTFY_TOPIC_FOOTBALL = os.environ.get("NTFY_TOPIC_FOOTBALL", "")

# Weekday numbers use datetime.weekday(): Mon=0 ... Sun=6. See RULES_FOOTBALL.md Section 6.
SCAN_CHECKPOINTS_ET = [
    (1, 10, 0),   # Tue 10:00 -- injuries firming up, first-pass scan
    (2, 10, 0),   # Wed 10:00
    (3, 14, 0),   # Thu 14:00 -- short-week TNF mini-scan
    (4, 16, 0),   # Fri 16:00 -- final practice report locks/kills injury edges
    (5, 18, 0),   # Sat 18:00 -- lock the Sunday slate
    (0, 14, 0),   # Mon 14:00 -- MNF scan
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
    """Hasn't kicked off yet. Football has no LEAD_HOURS gate like MLB -- the weekly
    checkpoint schedule itself is the timing control (RULES_FOOTBALL.md Section 6)."""
    if not game.get("start_utc"):
        return False
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(game["start_utc"].replace("Z", "+00:00"))
    return start > now


def build_candidate(game, injuries_by_team, ratings, league_avg, weather_cache):
    """One shared signal dict per game, fed to all three graders -- each reads only the
    fields relevant to it (model_football.py's cat_* functions), same pattern as the MLB
    model's totals_lean() reading a subset of a shared row."""
    home, away = game["home"], game["away"]
    home_stad = stadiums_football.for_team(home) or {}
    away_stad = stadiums_football.for_team(away) or {}
    roof = home_stad.get("roof", game.get("roof")) or "outdoor"

    wind_mph = temp_f = precip = None
    if roof == "outdoor" and game.get("start_utc") and home_stad.get("lat") is not None:
        key = (round(home_stad["lat"], 2), round(home_stad["lon"], 2), game["start_utc"])
        if key not in weather_cache:
            try:
                when = datetime.fromisoformat(game["start_utc"].replace("Z", "+00:00"))
                weather_cache[key] = fetch_weather.forecast_at(home_stad["lat"], home_stad["lon"], when)
            except Exception as e:
                print(f"weather fetch failed for {away}@{home} (non-fatal, skipping weather this run): {e}")
                weather_cache[key] = None
        fc = weather_cache[key]
        if fc:
            wind_mph, temp_f = fc.get("wind_mph"), fc.get("temp_f")
            precip = bool(fc.get("short") and any(w in fc["short"].lower() for w in ("rain", "snow", "storm", "shower")))

    return {
        "sport": "nfl", "home": home, "away": away,
        "home_rating": ratings.get(home), "away_rating": ratings.get(away),
        "league_avg_rating": league_avg,
        "home_injury_burden": model_football.injury_burden(injuries_by_team.get(home)) if injuries_by_team else None,
        "away_injury_burden": model_football.injury_burden(injuries_by_team.get(away)) if injuries_by_team else None,
        "home_rest": game.get("home_rest"), "away_rest": game.get("away_rest"),
        "div_game": game.get("div_game", False),
        "roof": roof,
        "away_team_is_dome_team": away_stad.get("roof") != "outdoor" if away_stad else False,
        "wind_mph": wind_mph, "temp_f": temp_f, "precip": precip,
    }


def _entry_for(game, odds):
    away_nick = fetch_nfl.TEAM_NICKNAME.get(game["away"])
    home_nick = fetch_nfl.TEAM_NICKNAME.get(game["home"])
    entries = odds.get((away_nick, home_nick), [])
    return fetch_odds_football.closest(entries, game["start_utc"]) or {}


def _price_for(market, side, entry):
    """(price, point) for the side the model picked -- point is display-only, price is
    what staking is computed on."""
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


def record_opens(games, odds, opens, week_key):
    if opens.get("week") != week_key:
        opens = {"week": week_key, "lines": {}}
    lines = opens["lines"]
    for g in games:
        entry = _entry_for(g, odds)
        if not entry:
            continue
        lines.setdefault(g["game_id"], {
            "home_ml": entry.get("home_ml"), "away_ml": entry.get("away_ml"),
            "home_spread_price": entry.get("home_spread_price"), "away_spread_price": entry.get("away_spread_price"),
            "over_price": entry.get("over_price"), "under_price": entry.get("under_price"),
        })
    return opens


def _open_price(opens, game_id, market, side):
    o = opens.get("lines", {}).get(game_id, {})
    if market == "ml":
        return o.get("home_ml") if side == "home" else o.get("away_ml")
    if market == "spread":
        return o.get("home_spread_price") if side == "home" else o.get("away_spread_price")
    if market == "total":
        return o.get("over_price") if side == "over" else o.get("under_price")
    return None


def grade_game(game, candidate, odds, opens):
    """Grade all three markets for one game. Returns a list of result dicts (only
    verdict CONFIRMED/LEAN after the RLM overlay are meant to be notified/staked --
    NOTE/PASS are still returned for card logging)."""
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


def _week_key(games):
    if not games:
        return None
    g0 = games[0]
    return f"{g0['season']}-wk{g0['week']}"


def main():
    if not market_hours_open():
        print("Not within grace of an NFL scan checkpoint — skipping, no API calls made.")
        return
    record_run()

    games = [g for g in fetch_nfl.week_games() if in_window(g)]
    if not games:
        print("No upcoming NFL games in the current week window.")
        return
    week_key = _week_key(games)
    season, week = games[0]["season"], games[0]["week"]

    try:
        odds = fetch_odds_football.football_odds("nfl")
    except Exception as e:
        print(f"Odds fetch failed, skipping this run: {e}")
        return

    opens = record_opens(games, odds, load_json(OPENS_FILE, {}), week_key)
    save_json(OPENS_FILE, opens)

    try:
        injuries_by_team = fetch_nfl.injuries(season, week)
    except Exception as e:
        print(f"Injury fetch failed, skipping injury signal this run: {e}")
        injuries_by_team = {}

    try:
        ratings = fetch_nfl.team_power_ratings(season, through_week=week)
    except Exception as e:
        print(f"Power-rating fetch failed, skipping mismatch signal this run: {e}")
        ratings = {}
    league_avg = sum(ratings.values()) / len(ratings) if ratings else 0.0

    weather_cache = {}
    state = load_json(STATE_FILE, {})
    sent = set(state.get("sent", [])) if state.get("week") == week_key else set()

    all_results = []
    for game in games:
        candidate = build_candidate(game, injuries_by_team, ratings, league_avg, weather_cache)
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
            ZoneInfo("America/New_York")).strftime("%a %-I:%M %p ET")
        title_line = (f"[NFL] {game['away']} @ {game['home']} — {market.upper()}  "
                      f"{market_result['verdict']}\n{sel} {price_str} ({stake}) — {when}")
        reason_line = market_result["reason"] + (f"  [{market_result['rlm']['tag']}]" if market_result.get("rlm") else "")
        ntfy_lines.append(f"{title_line}\n{reason_line}")
        sent.add(key)
        fresh.append((game, market, market_result))

    log_card(all_results)

    if not fresh:
        print("No new qualifying NFL plays this scan.")
        return

    body = "\n\n".join(ntfy_lines)
    title = f"🏈 {len(fresh)} NFL play(s) — week {week}"
    if NTFY_TOPIC_FOOTBALL:
        notify.push(title, body, topic=NTFY_TOPIC_FOOTBALL, tag="football")
    else:
        print("NTFY_TOPIC_FOOTBALL not set — skipping ntfy push (picks are still logged to the card file).")

    save_json(STATE_FILE, {"week": week_key, "sent": sorted(sent)})
    print("Notified:\n" + body)


def log_card(all_results):
    """Append every graded row (including NOTE/PASS) to card_nfl_<date>.json so
    grade_football.py can settle CONFIRMED/LEAN plays and the full read stays auditable."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"card_nfl_{date}.json"
    card = load_json(path, {"date": date, "plays": []})
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
