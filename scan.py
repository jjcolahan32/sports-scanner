"""
scan.py — the unattended job. Runs on a schedule (see .github/workflows/scan.yml).

Flow each run:
  1. Pull today's MLB games + probable pitchers (start times) from MLB StatsAPI.
  2. Keep games starting within LEAD_HOURS whose probable pitcher is on a vetted list.
  3. Pull consensus moneylines, build a slate row per qualifying game.
  4. Grade through the existing model (model.py).
  5. Notify NEW plays only (dedupe by game_pk in state.json), via ntfy.

Timezone-proof: uses each game's real UTC start time — no day-of-week guessing.
"""
import os, json, sys
from datetime import datetime, timezone

from model import run, american_to_stake, cap_rule, LEGIT_ARMS, MIRAGES, REVERSE_MIRAGES
import fetch_mlb, fetch_odds, notify, rlm

LEAD_HOURS = float(os.environ.get("LEAD_HOURS", "4"))   # notify within N hours of first pitch
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
OPENS_FILE = os.environ.get("OPENS_FILE", "opens.json")   # opening-line snapshots (for RLM)
PUBLIC_FILE = os.environ.get("PUBLIC_FILE", "public.json")  # OPTIONAL bet% you supply
VETTED = LEGIT_ARMS | MIRAGES | REVERSE_MIRAGES


# ---------- pure, testable core -------------------------------------------
def hours_until(start_utc, now=None):
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
    return (start - now).total_seconds() / 3600.0


def _last(name):
    return (name or "").strip().lower()


def in_window(game, now=None):
    """True if game starts within LEAD_HOURS (and hasn't started) and is a real game."""
    if game.get("game_type") not in (None, "R", "F", "D", "L", "W"):  # skip A=allstar, E=exhib
        return False
    h = hours_until(game["start_utc"], now)
    return 0 < h <= LEAD_HOURS


def qualifying_pitchers(game):
    """Yield (side, pitcher_full, team) for probable pitchers on a vetted list."""
    for side, pk, team in (("away", game.get("away_prob"), game.get("away")),
                           ("home", game.get("home_prob"), game.get("home"))):
        if pk and _last(pk).split()[-1] in {v.split()[-1] for v in VETTED} and _last(pk) in _matchset(pk):
            yield side, pk, team


def _matchset(pitcher_full):
    """Match a full name against the vetted lists' 'X. Last' or 'last' forms."""
    last = _last(pitcher_full).split()[-1]
    hits = set()
    for v in VETTED:
        if v.split()[-1] == last:
            hits.add(v)
            hits.add(_last(pitcher_full))
    return hits


def _is_mirage(full):
    last = _last(full).split()[-1]
    return any(v.split()[-1] == last for v in MIRAGES)


def build_slate(games, odds, opens=None, public=None, now=None):
    """Turn qualifying games into model slate rows + market context for RLM.

    Back a legit/reverse-mirage arm -> bet HIS team's ML.
    Fade a mirage arm            -> bet the OPPONENT's ML.
    """
    opens = opens or {}
    public = public or {}
    rows, meta = [], []
    for g in games:
        if not in_window(g, now):
            continue
        key = f"{fetch_odds._norm(g['away'])}@{fetch_odds._norm(g['home'])}"
        o = odds.get((fetch_odds._norm(g["away"]), fetch_odds._norm(g["home"])), {})
        for side, pk, team in qualifying_pitchers(g):
            opp_side = "home" if side == "away" else "away"
            if _is_mirage(pk):                      # fade -> opponent
                bet_side, bet_team = opp_side, g[opp_side]
                note = f"(fade {_fmt(pk)})"
            else:                                   # back -> his team
                bet_side, bet_team = side, team
                note = f"(back {_fmt(pk)})"
            ml = o.get(f"{bet_side}_ml")
            if ml is None:
                continue
            open_ml = opens.get(key, {}).get(f"{bet_side}_ml", ml)   # fall back to current
            pub = (public.get(str(g["game_pk"])) or {}).get(bet_side)  # optional
            rows.append({"sport": "mlb", "selection": f"{bet_team} ML {note}",
                         "pitcher": _fmt(pk), "odds": ml, "market": "ml",
                         "venue": "coors" if "Coors" in g["venue"] else g["venue"]})
            meta.append({"game_pk": g["game_pk"], "selection": f"{bet_team} ML",
                         "bet_side": bet_side, "bet_team": bet_team,
                         "start_utc": g["start_utc"],
                         "open_ml": open_ml, "cur_ml": ml, "public_pct": pub})
    return rows, meta


def record_opens(games, odds, opens):
    """First line seen for each game today becomes the 'open'. Date-aware."""
    if opens.get("date") != _today():
        opens = {"date": _today(), "lines": {}}
    lines = opens["lines"]
    for g in games:
        key = f"{fetch_odds._norm(g['away'])}@{fetch_odds._norm(g['home'])}"
        o = odds.get((fetch_odds._norm(g["away"]), fetch_odds._norm(g["home"])), {})
        if key not in lines and (o.get("home_ml") is not None or o.get("away_ml") is not None):
            lines[key] = {"home_ml": o.get("home_ml"), "away_ml": o.get("away_ml")}
    return opens


def _fmt(full):
    """'Aaron Nola' -> 'A. Nola' to match list style; leave single-token names alone."""
    parts = full.split()
    return f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else full


def apply_rlm(graded, meta):
    """Attach RLM tag to each row and adjust PLAY->REVIEW on market conflict."""
    for row, m in zip(graded, meta):
        if row["verdict"] != "PLAY":
            row["rlm"] = None
            continue
        sig = rlm.evaluate(m["open_ml"], m["cur_ml"], m.get("public_pct"))
        new_verdict, note = rlm.verdict_adjust(row["verdict"], sig["tag"])
        row["verdict"] = new_verdict
        row["rlm"] = sig
        row["rlm_note"] = note
    return graded


def new_plays(graded, meta, sent):
    """Return fresh PLAY/REVIEW rows whose game_pk hasn't been notified yet."""
    fresh = []
    for row, m in zip(graded, meta):
        if row["verdict"] in ("PLAY", "REVIEW") and str(m["game_pk"]) not in sent:
            fresh.append((row, m))
    return fresh
# --------------------------------------------------------------------------


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state():
    """Return sent game_pks for today; auto-resets when the date rolls over."""
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
        return set(s.get("sent", [])) if s.get("date") == _today() else set()
    except FileNotFoundError:
        return set()


def save_state(sent):
    with open(STATE_FILE, "w") as f:
        json.dump({"date": _today(), "sent": sorted(sent)}, f)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def main():
    games = fetch_mlb.todays_games()
    odds = fetch_odds.mlb_moneylines()

    opens = record_opens(games, odds, load_json(OPENS_FILE, {}))   # snapshot opening lines
    save_json(OPENS_FILE, opens)
    public = load_json(PUBLIC_FILE, {})                            # optional bet% you supply

    slate, meta = build_slate(games, odds, opens["lines"], public)
    graded, must_parlay = run(slate)
    graded = apply_rlm(graded, meta)                              # market overlay
    sent = load_state()
    fresh = new_plays(graded, meta, sent)

    if not fresh:
        print("No new qualifying plays this scan.")
        return

    lines = []
    for row, m in fresh:
        flag = "🔎REVIEW" if row["verdict"] == "REVIEW" else "PLAY"
        tag = ""
        if row.get("rlm"):
            tag = f"  [{row['rlm']['tag']} {row['rlm']['detail']}]"
        note = f"  {row.get('rlm_note','')}" if row.get("rlm_note") else ""
        lines.append(f"{flag}: {row['sel']} {row['odds']:+d} "
                     f"(risk {row['risk']}u/win {row['to_win']}u){tag}\n"
                     f"   {row['reason']}{note}")
        sent.add(str(m["game_pk"]))
    if len(must_parlay) >= 2:
        lines.append("🔗 Cap rule: parlay the -150+ favs together.")
    elif len(must_parlay) == 1:
        lines.append("⚠️ Lone -150+ fav — parlay or log override.")

    body = "\n".join(lines)
    notify.push(f"⚾ {len(fresh)} play(s) — starts within {int(LEAD_HOURS)}h", body)
    log_card(fresh)
    save_state(sent)
    print("Notified:\n" + body)


def log_card(fresh):
    """Append newly-fired plays to card_<date>.json so the nightly grader can settle them."""
    path = f"card_{_today()}.json"
    card = load_json(path, {"date": _today(), "plays": []})
    seen = {str(p["game_pk"]) for p in card["plays"]}
    for row, m in fresh:
        if str(m["game_pk"]) in seen:
            continue
        card["plays"].append({
            "game_pk": m["game_pk"], "start_utc": m["start_utc"],
            "bet_team": m["bet_team"], "bet_side": m["bet_side"],
            "selection": row["sel"], "odds": row["odds"],
            "risk": row["risk"], "to_win": row["to_win"], "cap": row["cap"],
            "verdict": row["verdict"],
            "rlm_tag": (row.get("rlm") or {}).get("tag", "NEUTRAL"),
            "graded": False, "result": None,
        })
    save_json(path, card)


if __name__ == "__main__":
    main()
