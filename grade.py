"""
grade.py — nightly settlement.

Reads every card_<date>.json (moneyline) and card_totals_<date>.json
(totals), finds ungraded plays whose games are Final, settles each, updates:
  - the MLB model-performance ledger (units) -- moneylines and totals tracked
    separately (different bet types, different variance)
  - a per-RLM-tag breakdown (so you can see if STEAM/RLM-FOR plays beat neutral ones)
  - a per-star breakdown (so you can see if the 1-5 star confidence rating
    actually tracks real performance), combined across both markets
and pushes the day's summary to your phone.

Notes / honesty:
  - This grades the MODEL's recommended straight singles. It is a model-performance
    ledger, separate from your manual play610 unit ledger.
  - Cap-rule parlay legs (odds harder than -150) are settled for W/L info only and
    are NOT added to the unit total — you build those parlays manually, so their real
    payout depends on how you combined them. They're reported under "settle manually".
  - REVIEW plays (market opposed) are graded and bucketed by their tag, so you can see
    how the "market said pass" spots actually turned out.
"""
import os, json, glob
from datetime import datetime, timezone

import fetch_mlb, notify, discord_notify

LEDGER_FILE = os.environ.get("LEDGER_FILE", "ledger.json")

# Broad grading window in US Eastern time (DST-aware): 6pm-4am ET, roughly
# every 2h within it. Only enforced on scheduled (cron) runs; manual
# dispatch and local runs always proceed.
#
# Not gated on an exact-hour match anymore. GitHub's `schedule:` trigger is
# documented as best-effort, and in practice here it dropped the large
# majority of its hourly ticks -- overnight on 2026-07-18 zero of the
# 6pm-4am checkpoints actually fired. Fixed the same way as scan.py's
# market_hours_open(): stay inside the broad window and fire on whichever
# tick actually lands, throttled to roughly once every MIN_GAP_MINUTES by a
# persisted last-run timestamp, so a dropped tick just delays to the next
# one that lands instead of silently losing that entire checkpoint.
LAST_RUN_FILE = os.environ.get("GRADE_LAST_RUN_FILE", "last_grade.json")
MIN_GAP_MINUTES = 100


def grade_hours_open(now_utc=None):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    from zoneinfo import ZoneInfo
    now_utc = now_utc or datetime.now(timezone.utc)
    et_hour = now_utc.astimezone(ZoneInfo("America/New_York")).hour
    if not (et_hour >= 18 or et_hour <= 4):
        return False
    last = load_json(LAST_RUN_FILE, {}).get("at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now_utc - last_dt).total_seconds() < MIN_GAP_MINUTES * 60:
                return False
        except Exception:
            pass
    return True


def record_run(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    save_json(LAST_RUN_FILE, {"at": now_utc.isoformat()})


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
    return {"mlb_units": 0.0,
            "record": {"w": 0, "l": 0, "push": 0},
            "by_tag": {},                              # RLM tag -> {w,l,units} (moneylines only)
            "by_stars": {},                            # "1".."5" -> {w,l,units} (both markets)
            "totals_units": 0.0,                       # separate P&L for over/under plays
            "totals_record": {"w": 0, "l": 0, "push": 0},
            "parlay_legs": {"w": 0, "l": 0},            # info only
            "discord_units": 0.0,                       # running total for Discord-tracked plays only
            "discord_record": {"w": 0, "l": 0, "push": 0},  # (both markets combined, cumulative across nights)
            "history": []}                              # per-day rows


def _migrate(ledger):
    """Older ledgers predate by_stars/totals_* -- fill in blanks so grading
    old ledger.json files doesn't KeyError."""
    blank = blank_ledger()
    for key, default in blank.items():
        ledger.setdefault(key, default)
    return ledger


def winner_side(res):
    hs, as_ = res.get("home_score"), res.get("away_score")
    if hs is None or as_ is None or hs == as_:
        return None
    return "home" if hs > as_ else "away"


def settle_play(play, res):
    """Return ('win'/'loss'/None, units_delta) for a moneyline play.
    units_delta is 0 for parlay legs."""
    side = winner_side(res)
    if side is None:
        return None, 0.0
    won = (side == play["bet_side"])
    is_parlay = play.get("cap") == "must_parlay"
    if is_parlay:
        return ("win" if won else "loss"), 0.0     # info only, not added to units
    delta = play["to_win"] if won else -play["risk"]
    return ("win" if won else "loss"), delta


def settle_total(play, res):
    """Return ('win'/'loss'/'push'/None, units_delta) for an over/under play."""
    hs, as_ = res.get("home_score"), res.get("away_score")
    line = play.get("total")
    if hs is None or as_ is None or line is None:
        return None, 0.0
    actual = hs + as_
    if actual == line:
        return "push", 0.0
    went_over = actual > line
    won = (went_over and play["side"] == "Over") or (not went_over and play["side"] == "Under")
    return ("win" if won else "loss"), (play["to_win"] if won else -play["risk"])


def _get_result(results_cache, card_date, play):
    """card_date -- not the play's own start_utc -- is what MLB's schedule
    API actually indexes this game under. A game starting at, say, 10pm ET
    is already past midnight UTC, so start_utc's calendar date is one day
    ahead of the date todays_games() queried when this play was originally
    found and logged; querying that derived date silently never finds the
    game, so the play never grades. card_date (the date baked into the
    card_<date>.json filename) is guaranteed to match, since it's the exact
    date todays_games() was called with in the first place."""
    if card_date not in results_cache:
        results_cache[card_date] = fetch_mlb.results_for_date(card_date)
    res = results_cache[card_date].get(play["game_pk"])
    return res if res and res.get("status") == "Final" else None


def _bucket(store, key):
    return store.setdefault(key, {"w": 0, "l": 0, "units": 0.0})


def grade_moneylines(ledger, results_cache, day, discord_sent):
    for path in sorted(p for p in glob.glob("card_*.json") if "totals" not in p):
        card_date = path[len("card_"):-len(".json")]
        card = load_json(path, None)
        if not card:
            continue
        changed = False
        for play in card["plays"]:
            if play.get("graded"):
                continue
            res = _get_result(results_cache, card_date, play)
            if not res:
                continue

            outcome, delta = settle_play(play, res)
            if outcome is None:
                continue
            play["graded"] = True
            play["result"] = {"outcome": outcome,
                              "score": f"{res['away']} {res['away_score']}–{res['home_score']} {res['home']}"}
            changed = True
            is_discord = str(play["game_pk"]) in discord_sent

            tag = play.get("rlm_tag", "NEUTRAL")
            tag_bucket = _bucket(ledger["by_tag"], tag)
            stars = play.get("stars", 3)
            star_bucket = _bucket(ledger["by_stars"], str(stars))
            if play.get("cap") == "must_parlay":
                ledger["parlay_legs"]["w" if outcome == "win" else "l"] += 1
                mark = "🔗leg"
            else:
                ledger["mlb_units"] = round(ledger["mlb_units"] + delta, 2)
                ledger["record"]["w" if outcome == "win" else "l"] += 1
                tag_bucket["w" if outcome == "win" else "l"] += 1
                tag_bucket["units"] = round(tag_bucket["units"] + delta, 2)
                star_bucket["w" if outcome == "win" else "l"] += 1
                star_bucket["units"] = round(star_bucket["units"] + delta, 2)
                day["w" if outcome == "win" else "l"] += 1
                day["units"] = round(day["units"] + delta, 2)
                mark = f"{delta:+.2f}u"
                if is_discord:
                    day["discord_w" if outcome == "win" else "discord_l"] += 1
                    day["discord_units"] = round(day["discord_units"] + delta, 2)
                    ledger["discord_units"] = round(ledger["discord_units"] + delta, 2)
                    ledger["discord_record"]["w" if outcome == "win" else "l"] += 1
            line = (f"{'✅' if outcome=='win' else '❌'} {play['selection']} "
                   f"{play['odds']:+d} [{tag}] {'★'*stars} {mark}")
            day["lines"].append(line)
            if is_discord:
                day["discord_lines"].append(line)
        if changed:
            save_json(path, card)


def grade_totals(ledger, results_cache, day, discord_sent):
    for path in sorted(glob.glob("card_totals_*.json")):
        card_date = path[len("card_totals_"):-len(".json")]
        card = load_json(path, None)
        if not card:
            continue
        changed = False
        for play in card["plays"]:
            if play.get("graded"):
                continue
            res = _get_result(results_cache, card_date, play)
            if not res:
                continue

            outcome, delta = settle_total(play, res)
            if outcome is None:
                continue
            play["graded"] = True
            play["result"] = {"outcome": outcome,
                              "score": f"{res['away']} {res['away_score']}–{res['home_score']} {res['home']}"}
            changed = True
            is_discord = str(play["game_pk"]) in discord_sent

            stars = play.get("stars", 3)
            if outcome == "push":
                ledger["totals_record"]["push"] += 1
                if is_discord:
                    ledger["discord_record"]["push"] += 1
                line = f"➖ {play['selection']} push"
                day["lines"].append(line)
                if is_discord:
                    day["discord_lines"].append(line)
            else:
                star_bucket = _bucket(ledger["by_stars"], str(stars))
                ledger["totals_units"] = round(ledger["totals_units"] + delta, 2)
                ledger["totals_record"]["w" if outcome == "win" else "l"] += 1
                star_bucket["w" if outcome == "win" else "l"] += 1
                star_bucket["units"] = round(star_bucket["units"] + delta, 2)
                day["w" if outcome == "win" else "l"] += 1
                day["units"] = round(day["units"] + delta, 2)
                if is_discord:
                    day["discord_w" if outcome == "win" else "discord_l"] += 1
                    day["discord_units"] = round(day["discord_units"] + delta, 2)
                    ledger["discord_units"] = round(ledger["discord_units"] + delta, 2)
                    ledger["discord_record"]["w" if outcome == "win" else "l"] += 1
                line = (f"{'✅' if outcome=='win' else '❌'} {play['selection']} "
                       f"{play['odds']:+d} [TOTALS] {'★'*stars} {delta:+.2f}u")
                day["lines"].append(line)
                if is_discord:
                    day["discord_lines"].append(line)
        if changed:
            save_json(path, card)


def grade_all():
    ledger = _migrate(load_json(LEDGER_FILE, blank_ledger()))
    results_cache = {}
    day = {"w": 0, "l": 0, "units": 0.0, "lines": [],
           "discord_w": 0, "discord_l": 0, "discord_units": 0.0, "discord_lines": []}
    discord_sent = discord_notify.load_sent()
    grade_moneylines(ledger, results_cache, day, discord_sent)
    grade_totals(ledger, results_cache, day, discord_sent)
    return ledger, day


def main():
    if not grade_hours_open():
        print("Outside grading hours (6pm-4am ET) — skipping, no API calls made.")
        return
    record_run()

    ledger, day = grade_all()
    if not day["lines"]:
        print("Nothing new to grade.")
        return
    save_json(LEDGER_FILE, ledger)

    tag_lines = [f"{tag}: {b['w']}-{b['l']} ({b['units']:+.2f}u)"
                 for tag, b in sorted(ledger["by_tag"].items())]
    star_lines = [f"{'★'*int(n)}: {b['w']}-{b['l']} ({b['units']:+.2f}u)"
                  for n, b in sorted(ledger["by_stars"].items(), key=lambda kv: -int(kv[0]))]

    body = (f"{day['w']}-{day['l']}  day P&L {day['units']:+.2f}u\n"
            + "\n".join(day["lines"])
            + f"\n\nMLB model ledger: {ledger['mlb_units']:+.2f}u "
              f"({ledger['record']['w']}-{ledger['record']['l']})")
    if ledger["totals_record"]["w"] or ledger["totals_record"]["l"]:
        tr = ledger["totals_record"]
        body += f"\nTotals ledger: {ledger['totals_units']:+.2f}u ({tr['w']}-{tr['l']}, {tr['push']} push)"
    if ledger["parlay_legs"]["w"] or ledger["parlay_legs"]["l"]:
        pl = ledger["parlay_legs"]
        body += f"\n🔗 parlay legs {pl['w']}-{pl['l']} (settle manually)"
    if tag_lines:
        body += "\n— by tag —\n" + "\n".join(tag_lines)
    if star_lines:
        body += "\n— by stars —\n" + "\n".join(star_lines)

    ledger["history"].append({"graded_at": datetime.now(timezone.utc).isoformat(),
                              "w": day["w"], "l": day["l"], "units": day["units"]})
    save_json(LEDGER_FILE, ledger)
    notify.push(f"📊 Day graded: {day['units']:+.2f}u", body, tag="chart")

    # Discord only gets a recap of plays whose PLAY alert actually reached
    # Discord (see discord_notify.record_sent) -- not the full day's card,
    # so it never reports a settled result for a pick Discord never saw fire.
    #
    # Grading can optionally post to a separate Discord channel/webhook from
    # picks (DISCORD_GRADING_WEBHOOK_URL) -- set that secret once you're
    # ready to split "picks" and "grading" into their own channels; until
    # then it's unset and this falls back to the same webhook as picks.
    if day["discord_lines"]:
        discord_title = (f"📊 Day graded: {day['discord_w']}-{day['discord_l']} "
                         f"({day['discord_units']:+.2f}u)")
        dr = ledger["discord_record"]
        running = f"{dr['w']}-{dr['l']}" + (f", {dr['push']} push" if dr.get("push") else "")
        discord_body = ("\n".join(day["discord_lines"])
                         + f"\n\nRunning record: {running} ({ledger['discord_units']:+.2f}u)")
        grading_webhook = os.environ.get("DISCORD_GRADING_WEBHOOK_URL") or None
        discord_notify.push(discord_title, discord_body, webhook_url=grading_webhook)

    print("Graded:\n" + body)


if __name__ == "__main__":
    main()
