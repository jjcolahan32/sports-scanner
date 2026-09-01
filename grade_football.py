"""
grade_football.py — settlement for both card_nfl_<date>.json and card_cfb_<date>.json.
Separate ledger from the MLB model (ledger_football.json) -- RULES.md's own "ledgers
tracked separately per book" precedent applies here too (see grade.py, the MLB
equivalent this mirrors).

Honesty notes (same spirit as grade.py's own):
  - Only CONFIRMED plays are staked and count toward units. LEAN plays (CONFIRMED but
    RLM opposed -- RULES_FOOTBALL.md Section 3/4) are still settled W/L/push and
    bucketed, so you can see how the market-opposed spots actually turned out, but they
    never move the units ledger -- they were never staked in the first place.
  - Spread/total settle against the point captured AT THE TIME THE PICK FIRED (stored on
    the play itself), not today's closing number -- same "book the number you actually
    had" principle as any real bet.
"""
import os, json, glob
from datetime import datetime, timezone

import fetch_nfl, fetch_cfb, notify

LEDGER_FILE = os.environ.get("LEDGER_FOOTBALL_FILE", "ledger_football.json")
NTFY_TOPIC_FOOTBALL = os.environ.get("NTFY_TOPIC_FOOTBALL", "")

GRADE_CHECKPOINTS_ET = [(6, 0), (12, 0)]   # see grade.py's own for the external-cron rationale
CHECKPOINT_GRACE_MINUTES = 30
LAST_RUN_FILE = os.environ.get("GRADE_FOOTBALL_LAST_RUN_FILE", "last_grade_football.json")


def _et_now_and_today(now_utc):
    from zoneinfo import ZoneInfo
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    return et, et.strftime("%Y-%m-%d")


def _due_checkpoints(et, fired):
    now_minutes = et.hour * 60 + et.minute
    due = []
    for hh, mm in GRADE_CHECKPOINTS_ET:
        label = f"{hh:02d}:{mm:02d}"
        if label in fired:
            continue
        if 0 <= now_minutes - (hh * 60 + mm) <= CHECKPOINT_GRACE_MINUTES:
            due.append(label)
    return due


def grade_hours_open(now_utc=None):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    now_utc = now_utc or datetime.now(timezone.utc)
    et, today = _et_now_and_today(now_utc)
    state = load_json(LAST_RUN_FILE, {})
    fired = set(state.get("fired", [])) if state.get("date") == today else set()
    return bool(_due_checkpoints(et, fired))


def record_run(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    et, today = _et_now_and_today(now_utc)
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
        json.dump(obj, f, indent=2)


def blank_ledger():
    return {
        "units": 0.0, "record": {"w": 0, "l": 0, "push": 0},
        "by_sport": {}, "by_market": {}, "by_verdict": {}, "by_tag": {},
        "history": [],
    }


def _migrate(ledger):
    blank = blank_ledger()
    for key, default in blank.items():
        ledger.setdefault(key, default)
    return ledger


def _bucket(store, key):
    return store.setdefault(key, {"w": 0, "l": 0, "push": 0, "units": 0.0})


def settle_ml(play, home_score, away_score):
    if home_score == away_score:
        return None, 0.0
    won = (home_score > away_score) == (play["side"] == "home")
    return ("win" if won else "loss"), (play["to_win"] if won else -play["risk"])


def settle_spread(play, home_score, away_score):
    point = play.get("point")
    if point is None:
        return None, 0.0
    margin = home_score - away_score if play["side"] == "home" else away_score - home_score
    covered = margin + point
    if covered == 0:
        return "push", 0.0
    won = covered > 0
    return ("win" if won else "loss"), (play["to_win"] if won else -play["risk"])


def settle_total(play, home_score, away_score):
    line = play.get("point")
    if line is None:
        return None, 0.0
    actual = home_score + away_score
    if actual == line:
        return "push", 0.0
    went_over = actual > line
    won = (went_over and play["side"] == "over") or (not went_over and play["side"] == "under")
    return ("win" if won else "loss"), (play["to_win"] if won else -play["risk"])


SETTLERS = {"ml": settle_ml, "spread": settle_spread, "total": settle_total}


def _results_for(sport, season, results_cache):
    key = (sport, season)
    if key not in results_cache:
        try:
            games = fetch_nfl.season_games(season) if sport == "nfl" else fetch_cfb.season_games(season)
        except Exception as e:
            print(f"{sport} {season} results fetch failed (will retry next grading run): {e}")
            games = []
        results_cache[key] = {g["game_id"]: g for g in games}
    return results_cache[key]


def grade_sport(sport, ledger, results_cache, day):
    for path in sorted(glob.glob(f"card_{sport}_*.json")):
        card = load_json(path, None)
        if not card:
            continue
        changed = False
        for play in card["plays"]:
            if play.get("graded") or play["verdict"] not in ("CONFIRMED", "LEAN"):
                continue
            games = _results_for(sport, play["start_utc"][:4], results_cache)
            res = games.get(play["game_id"])
            if not res:
                continue
            hs, aws = res.get("home_score"), res.get("away_score")
            if hs is None or aws is None:
                continue

            outcome, delta = SETTLERS[play["market"]](play, hs, aws)
            if outcome is None:
                continue
            if play["verdict"] != "CONFIRMED":
                delta = 0.0   # LEAN settles for record only, never staked -- see module docstring
            play["graded"] = True
            play["result"] = {"outcome": outcome, "score": f"{res['away']} {aws}–{hs} {res['home']}"}
            changed = True

            outcome_key = "push" if outcome == "push" else ("w" if outcome == "win" else "l")
            if outcome != "push":
                ledger["units"] = round(ledger["units"] + delta, 2)
                day["units"] = round(day["units"] + delta, 2)
            ledger["record"][outcome_key] += 1
            day[outcome_key] += 1

            for store, key in ((ledger["by_sport"], sport), (ledger["by_market"], play["market"]),
                                (ledger["by_verdict"], play["verdict"]), (ledger["by_tag"], play.get("rlm_tag", "NEUTRAL"))):
                b = _bucket(store, key)
                b[outcome_key] += 1
                if outcome != "push":
                    b["units"] = round(b["units"] + delta, 2)

            mark = f"{delta:+.2f}u" if outcome != "push" else "push"
            icon = {"win": "✅", "loss": "❌", "push": "➖"}[outcome]
            tag = "" if play["verdict"] == "CONFIRMED" else f" [{play['verdict']}]"
            price_str = f"{play['price']:+d} " if play.get("price") is not None else ""
            day["lines"].append(
                f"{icon} [{sport.upper()}] {play['selection']} {price_str}"
                f"{play['market'].upper()}{tag} {mark}")
        if changed:
            save_json(path, card)


def grade_all():
    ledger = _migrate(load_json(LEDGER_FILE, blank_ledger()))
    results_cache = {}
    day = {"w": 0, "l": 0, "push": 0, "units": 0.0, "lines": []}
    grade_sport("nfl", ledger, results_cache, day)
    grade_sport("cfb", ledger, results_cache, day)
    return ledger, day


def main():
    if not grade_hours_open():
        print("Not within grace of a grading checkpoint — skipping, no API calls made.")
        return
    record_run()

    ledger, day = grade_all()
    if not day["lines"]:
        print("Nothing new to grade.")
        return
    save_json(LEDGER_FILE, ledger)

    sport_lines = [f"{s}: {b['w']}-{b['l']}-{b['push']} ({b['units']:+.2f}u)"
                   for s, b in sorted(ledger["by_sport"].items())]
    market_lines = [f"{m}: {b['w']}-{b['l']}-{b['push']} ({b['units']:+.2f}u)"
                     for m, b in sorted(ledger["by_market"].items())]

    body = (f"{day['w']}-{day['l']}-{day['push']}  day P&L {day['units']:+.2f}u\n"
            + "\n".join(day["lines"])
            + f"\n\nFootball model ledger: {ledger['units']:+.2f}u "
              f"({ledger['record']['w']}-{ledger['record']['l']}-{ledger['record']['push']})")
    if sport_lines:
        body += "\n— by sport —\n" + "\n".join(sport_lines)
    if market_lines:
        body += "\n— by market —\n" + "\n".join(market_lines)

    ledger["history"].append({"graded_at": datetime.now(timezone.utc).isoformat(),
                              "w": day["w"], "l": day["l"], "push": day["push"], "units": day["units"]})
    save_json(LEDGER_FILE, ledger)

    if NTFY_TOPIC_FOOTBALL:
        notify.push(f"🏈 Day graded: {day['units']:+.2f}u", body, topic=NTFY_TOPIC_FOOTBALL, tag="football")
    else:
        print("NTFY_TOPIC_FOOTBALL not set — skipping ntfy push.")
    print("Graded:\n" + body)


if __name__ == "__main__":
    main()
