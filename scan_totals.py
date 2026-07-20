"""
scan_totals.py — the unattended totals (over/under) job. Separate cadence
from scan.py's moneyline scan (see .github/workflows/scan_totals.yml) because
fetching the totals market costs its own Odds API quota unit per request --
running it every 2h like moneylines would blow through the free tier.

Flow each run:
  1. Pull today's remaining MLB games + probable pitchers from MLB StatsAPI.
  2. Pull the totals (over/under) market from The Odds API.
  3. For each game: look up park factor (ballparks.py), forecast wind/temp at
     first pitch (fetch_weather.py, NWS -- free but only covers ~7 days out),
     and both starters' quality (static lists + Savant ERA/xERA gap).
  4. Grade the composite lean through model.py (model.totals_lean /
     model.grade_total) -- same PLAY/PASS + Coors auto-pass + tight-under
     exception rules as the moneyline card.
  5. Notify NEW plays only (dedupe by game_pk in state_totals.json, separate
     from scan.py's dedupe so the two jobs never interfere), via ntfy.
"""
import os
from datetime import datetime, timezone

from model import run, totals_lean, star_rating
import fetch_mlb, fetch_odds, fetch_savant, fetch_weather, notify, discord_notify, ballparks
from scan import in_window, _fmt, dynamic_match, _today, load_json, save_json, market_hours_open, record_run, _star_str

STATE_FILE = os.environ.get("TOTALS_STATE_FILE", "state_totals.json")
LAST_RUN_FILE = os.environ.get("TOTALS_LAST_RUN_FILE", "last_totals.json")  # own file -- separate cadence tracking from scan.py
TOTALS_LEAD_HOURS = float(os.environ.get("TOTALS_LEAD_HOURS", "20"))  # wide window: only runs 2x/day


def build_totals_slate(games, totals_odds, savant_stats, now=None):
    """Turn today's remaining games into totals slate rows + meta for logging."""
    now = now or datetime.now(timezone.utc)
    rows, meta = [], []
    for g in games:
        h = (datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")) - now).total_seconds() / 3600.0
        if not (0 < h <= TOTALS_LEAD_HOURS):
            continue
        if g.get("game_type") not in (None, "R", "F", "D", "L", "W"):
            continue
        home, away = g["home"], g["away"]
        park = ballparks.for_team(home)
        if not park:
            continue
        entries = totals_odds.get((fetch_odds._norm(away), fetch_odds._norm(home)), [])
        line = fetch_odds.closest(entries, g["start_utc"])
        if not line or line.get("point") is None:
            continue

        # Roofed/domed parks: ambient outdoor wind/temp isn't a reliable read on
        # in-stadium conditions (no live open/closed roof status available), so
        # don't let outdoor weather vote on an indoor game -- park factor and
        # pitcher quality still apply.
        fc = None
        if not park.get("roof"):
            try:
                start = datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00"))
                fc = fetch_weather.forecast_at(park["lat"], park["lon"], start)
            except Exception:
                fc = None
        wind_out = (fetch_weather.wind_out_component(fc["wind_from_deg"], fc["wind_mph"], park["orientation_deg"])
                    if fc and fc.get("wind_from_deg") is not None else None)
        temp_f = fc["temp_f"] if fc else None

        home_dyn = dynamic_match(g.get("home_prob") or "", savant_stats)
        away_dyn = dynamic_match(g.get("away_prob") or "", savant_stats)

        signal = {
            "park_factor": park["park_factor"], "wind_out_mph": wind_out, "temp_f": temp_f,
            "home_pitcher": g.get("home_prob"), "away_pitcher": g.get("away_prob"),
            "home_dyn_gap": home_dyn["gap"] if home_dyn else None,
            "away_dyn_gap": away_dyn["gap"] if away_dyn else None,
        }
        lean = totals_lean(signal)
        side = "Over" if lean > 0 else "Under" if lean < 0 else None
        price = line["over_price"] if side == "Over" else line["under_price"] if side == "Under" else None
        if side is None or price is None:
            continue

        row = {"sport": "mlb", "market": "total", "total": line["point"], "odds": price,
               "venue": "coors" if "Coors" in park["venue"] else park["venue"],
               "selection": f"{away} @ {home} {side} {line['point']}", **signal}
        rows.append(row)
        meta.append({"game_pk": g["game_pk"], "start_utc": g["start_utc"],
                     "home": home, "away": away, "side": side, "total": line["point"], "lean": lean,
                     "home_prob": g.get("home_prob"), "away_prob": g.get("away_prob")})
    return rows, meta


def load_state():
    try:
        s = load_json(STATE_FILE, None)
        if s is None:
            return set()
        return set(s.get("sent", [])) if s.get("date") == _today() else set()
    except Exception:
        return set()


def save_state(sent):
    save_json(STATE_FILE, {"date": _today(), "sent": sorted(sent)})


def log_totals_card(fresh):
    path = f"card_totals_{_today()}.json"
    card = load_json(path, {"date": _today(), "plays": []})
    seen = {str(p["game_pk"]) for p in card["plays"]}
    for row, m in fresh:
        if str(m["game_pk"]) in seen:
            continue
        card["plays"].append({
            "game_pk": m["game_pk"], "start_utc": m["start_utc"],
            "home": m["home"], "away": m["away"], "side": m["side"],
            "home_prob": m["home_prob"], "away_prob": m["away_prob"],
            "selection": row["sel"], "total": m.get("total"), "odds": row["odds"],
            "risk": row["risk"], "to_win": row["to_win"], "cap": row["cap"],
            "verdict": row["verdict"], "stars": row.get("stars", 3),
            "graded": False, "result": None,
        })
    save_json(path, card)


def main():
    if not market_hours_open(last_run_file=LAST_RUN_FILE):
        print("Outside active scan hours (11am-9pm ET) — skipping, no API calls made.")
        return
    record_run(last_run_file=LAST_RUN_FILE)

    games = fetch_mlb.todays_games()
    totals_odds = fetch_odds.mlb_totals()
    try:
        savant_stats = fetch_savant.season_pitcher_stats()
    except Exception as e:
        print(f"Savant fetch failed, skipping dynamic pitcher signal this run: {e}")
        savant_stats = {}

    slate, meta = build_totals_slate(games, totals_odds, savant_stats)
    graded, must_parlay = run(slate)
    for row, m in zip(graded, meta):
        row["stars"] = star_rating(totals_lean_score=m["lean"])
    sent = load_state()

    fresh = [(row, m) for row, m in zip(graded, meta)
             if row["verdict"] == "PLAY" and str(m["game_pk"]) not in sent]

    if not fresh:
        print("No new qualifying totals plays this scan.")
        return

    lines, discord_lines = [], []
    for row, m in fresh:
        pick = (f"PLAY: {row['sel']} {row['odds']:+d} "
                f"(risk {row['risk']}u/win {row['to_win']}u)  {_star_str(row['stars'])}")
        reason = row['reason']
        lines.append(f"{pick}\n   {reason}")
        discord_lines.append(f"**{pick}**\n{reason}")
        sent.add(str(m["game_pk"]))
    if len(must_parlay) >= 2:
        tail = "Cap rule: parlay the -150+ favs together."
        lines.append(tail); discord_lines.append(tail)
    elif len(must_parlay) == 1:
        tail = "Lone -150+ fav — parlay or log override."
        lines.append(tail); discord_lines.append(tail)

    body = "\n".join(lines)
    title = f"MLB totals: {len(fresh)} play(s)"
    notify.push(title, body, tag="chart")
    if discord_notify.push(title, "\n".join(discord_lines)):
        discord_notify.record_sent(str(m["game_pk"]) for _, m in fresh)
    log_totals_card(fresh)
    save_state(sent)
    print("Notified:\n" + body)


if __name__ == "__main__":
    main()
