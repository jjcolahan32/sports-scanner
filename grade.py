"""
grade.py — nightly settlement.

Reads every card_<date>.json, finds ungraded plays whose games are Final,
settles each (moneyline W/L), updates:
  - the MLB model-performance ledger (units)
  - a per-RLM-tag breakdown (so you can see if STEAM/RLM-FOR plays beat neutral ones)
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

import fetch_mlb, notify

LEDGER_FILE = os.environ.get("LEDGER_FILE", "ledger.json")


def _date_of(start_utc):
    return start_utc.replace("Z", "+00:00")[:10]


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
            "by_tag": {},                       # tag -> {w,l,units}
            "parlay_legs": {"w": 0, "l": 0},    # info only
            "history": []}                      # per-day rows


def winner_side(res):
    hs, as_ = res.get("home_score"), res.get("away_score")
    if hs is None or as_ is None or hs == as_:
        return None
    return "home" if hs > as_ else "away"


def settle_play(play, res):
    """Return ('win'/'loss'/None, units_delta). units_delta is 0 for parlay legs."""
    side = winner_side(res)
    if side is None:
        return None, 0.0
    won = (side == play["bet_side"])
    is_parlay = play.get("cap") == "must_parlay"
    if is_parlay:
        return ("win" if won else "loss"), 0.0     # info only, not added to units
    delta = play["to_win"] if won else -play["risk"]
    return ("win" if won else "loss"), delta


def grade_all():
    ledger = load_json(LEDGER_FILE, blank_ledger())
    # cache results per date so we hit the API once per date
    results_cache, day = {}, {"w": 0, "l": 0, "units": 0.0, "lines": []}

    for path in sorted(glob.glob("card_*.json")):
        card = load_json(path, None)
        if not card:
            continue
        changed = False
        for play in card["plays"]:
            if play.get("graded"):
                continue
            d = _date_of(play["start_utc"])
            if d not in results_cache:
                results_cache[d] = fetch_mlb.results_for_date(d)
            res = results_cache[d].get(play["game_pk"])
            if not res or res.get("status") != "Final":
                continue                                  # not done yet; try again next run

            outcome, delta = settle_play(play, res)
            if outcome is None:                           # tie/postponed edge case
                continue
            play["graded"] = True
            play["result"] = {"outcome": outcome,
                              "score": f"{res['away']} {res['away_score']}–{res['home_score']} {res['home']}"}
            changed = True

            tag = play.get("rlm_tag", "NEUTRAL")
            bucket = ledger["by_tag"].setdefault(tag, {"w": 0, "l": 0, "units": 0.0})
            if play.get("cap") == "must_parlay":
                ledger["parlay_legs"]["w" if outcome == "win" else "l"] += 1
                mark = "🔗leg"
            else:
                ledger["mlb_units"] = round(ledger["mlb_units"] + delta, 2)
                ledger["record"]["w" if outcome == "win" else "l"] += 1
                bucket["w" if outcome == "win" else "l"] += 1
                bucket["units"] = round(bucket["units"] + delta, 2)
                day["w" if outcome == "win" else "l"] += 1
                day["units"] = round(day["units"] + delta, 2)
                mark = f"{delta:+.2f}u"
            day["lines"].append(f"{'✅' if outcome=='win' else '❌'} {play['selection']} "
                                f"{play['odds']:+d} [{tag}] {mark}")
        if changed:
            save_json(path, card)

    return ledger, day


def main():
    ledger, day = grade_all()
    if not day["lines"]:
        print("Nothing new to grade.")
        return
    save_json(LEDGER_FILE, ledger)

    # RLM readout: are market-confirmed plays beating neutral?
    tag_lines = []
    for tag in sorted(ledger["by_tag"]):
        b = ledger["by_tag"][tag]
        tag_lines.append(f"{tag}: {b['w']}-{b['l']} ({b['units']:+.2f}u)")

    body = (f"{day['w']}-{day['l']}  day P&L {day['units']:+.2f}u\n"
            + "\n".join(day["lines"])
            + f"\n\nMLB model ledger: {ledger['mlb_units']:+.2f}u "
              f"({ledger['record']['w']}-{ledger['record']['l']})")
    if ledger["parlay_legs"]["w"] or ledger["parlay_legs"]["l"]:
        pl = ledger["parlay_legs"]
        body += f"\n🔗 parlay legs {pl['w']}-{pl['l']} (settle manually)"
    if tag_lines:
        body += "\n— by tag —\n" + "\n".join(tag_lines)

    ledger["history"].append({"graded_at": datetime.now(timezone.utc).isoformat(),
                              "w": day["w"], "l": day["l"], "units": day["units"]})
    save_json(LEDGER_FILE, ledger)
    notify.push(f"📊 Day graded: {day['units']:+.2f}u", body, tag="chart")
    print("Graded:\n" + body)


if __name__ == "__main__":
    main()
