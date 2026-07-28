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

from model import (run, american_to_stake, cap_rule, LEGIT_ARMS, MIRAGES, REVERSE_MIRAGES,
                    DYNAMIC_GAP, BULLPEN_EDGE_VETO, LINEUP_EDGE_VETO, star_rating)
import fetch_mlb, fetch_odds, fetch_savant, fetch_teamstats, notify, discord_notify, rlm

LEAD_HOURS = float(os.environ.get("LEAD_HOURS", "4"))   # notify within N hours of first pitch
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
OPENS_FILE = os.environ.get("OPENS_FILE", "opens.json")   # opening-line snapshots (for RLM)
PUBLIC_FILE = os.environ.get("PUBLIC_FILE", "public.json")  # OPTIONAL bet% you supply

# Exact scan checkpoints in US Eastern time (DST-aware) -- not a window,
# not "roughly every N hours": these specific times, and nothing else.
# Only enforced on scheduled (cron) runs; manual dispatch and local runs
# always proceed.
#
# GitHub's `schedule:` trigger is documented as best-effort and in practice
# drops a real fraction of ticks (confirmed here previously), so cron itself
# fires often (every 10 minutes, see scan.yml/scan_totals.yml) and this gate
# decides whether a given tick lands within CHECKPOINT_GRACE_MINUTES after
# one of these times. A late/dropped tick still catches the checkpoint on
# the next one that lands; each checkpoint fires at most once per day,
# tracked in last_run_file (resets at midnight ET).
SCAN_CHECKPOINTS_ET = [
    (11, 0), (12, 30), (14, 0), (17, 0), (18, 30), (20, 0), (21, 0),
]
CHECKPOINT_GRACE_MINUTES = 20   # tightest gap between checkpoints here is 90 min, plenty of margin
LAST_RUN_FILE = os.environ.get("LAST_RUN_FILE", "last_scan.json")


def _et_now_and_today(now_utc):
    from zoneinfo import ZoneInfo
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    return et, et.strftime("%Y-%m-%d")


def _due_checkpoints(et, fired):
    """Checkpoints (as 'HH:MM' labels) that are within grace and not yet
    fired today."""
    now_minutes = et.hour * 60 + et.minute
    due = []
    for hh, mm in SCAN_CHECKPOINTS_ET:
        label = f"{hh:02d}:{mm:02d}"
        if label in fired:
            continue
        if 0 <= now_minutes - (hh * 60 + mm) <= CHECKPOINT_GRACE_MINUTES:
            due.append(label)
    return due


def market_hours_open(now_utc=None, last_run_file=None):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    now_utc = now_utc or datetime.now(timezone.utc)
    et, today = _et_now_and_today(now_utc)
    state = load_json(last_run_file or LAST_RUN_FILE, {})
    fired = set(state.get("fired", [])) if state.get("date") == today else set()
    return bool(_due_checkpoints(et, fired))


def record_run(last_run_file=None, now_utc=None):
    """Mark whichever checkpoint(s) are due right now as fired for today --
    normally just one, but if a tick was delayed enough to straddle two
    checkpoints' grace windows, marks both so a later tick doesn't re-fire
    the earlier one."""
    now_utc = now_utc or datetime.now(timezone.utc)
    et, today = _et_now_and_today(now_utc)
    path = last_run_file or LAST_RUN_FILE
    state = load_json(path, {})
    fired = set(state.get("fired", [])) if state.get("date") == today else set()
    fired.update(_due_checkpoints(et, fired))
    save_json(path, {"date": today, "fired": sorted(fired)})


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


def _list_tag(full):
    """Cross-reference a pitcher's live-confirmed read against the
    hand-vetted RULES.md lists. Context for the notification only -- being
    on a list is no longer a firing gate by itself (see build_slate); every
    pitcher, listed or not, needs today's actual Savant gap to confirm the
    read before anything fires."""
    if not full:
        return None
    last = _last(full).split()[-1]
    if any(v.split()[-1] == last for v in MIRAGES):
        return "mirage"
    if any(v.split()[-1] == last for v in REVERSE_MIRAGES):
        return "reverse"
    if any(v.split()[-1] == last for v in LEGIT_ARMS):
        return "legit"
    return None


def team_support_ok(bet_team, opp_team, team_stats):
    """Supporting-cast confirmation, layered on top of the starter-gap edge:
    veto only when BOTH the bullpen AND the lineup point against the picked
    team relative to their opponent -- a single-metric disagreement isn't
    enough to kill an otherwise live starter-gap read, since either one
    alone can be noisy over a partial season. Missing stats for either team
    means benefit of the doubt (True), never a silent veto from bad data."""
    bet, opp = team_stats.get(bet_team) or {}, team_stats.get(opp_team) or {}
    bet_era, opp_era = bet.get("bullpen_era"), opp.get("bullpen_era")
    bet_ops, opp_ops = bet.get("batting_ops"), opp.get("batting_ops")
    if None in (bet_era, opp_era, bet_ops, opp_ops):
        return True
    bullpen_against = (bet_era - opp_era) >= BULLPEN_EDGE_VETO   # our pen meaningfully worse
    lineup_against = (opp_ops - bet_ops) >= LINEUP_EDGE_VETO      # our lineup meaningfully worse
    return not (bullpen_against and lineup_against)


def dynamic_match(pk, savant_stats):
    """Look up a probable pitcher's season ERA-xERA gap by last name.
    Disambiguates same-surname pitchers by first-name initial. Returns the
    stat dict (with 'gap') or None if not found / ambiguous."""
    parts = _last(pk).split()
    if not parts:
        return None
    last = parts[-1]
    candidates = savant_stats.get(last, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and len(parts) > 1:
        first_initial = parts[0][0]
        matches = [c for c in candidates if c["first"].strip().lower().startswith(first_initial)]
        if len(matches) == 1:
            return matches[0]
    return None


def build_slate(games, odds, opens=None, public=None, now=None, savant_stats=None, team_stats=None):
    """Turn qualifying games into model slate rows + market context for RLM.

    Back a legit/reverse-mirage arm -> bet HIS team's ML.
    Fade a mirage arm            -> bet the OPPONENT's ML.

    Being on a RULES.md list is no longer enough to fire by itself. Every
    probable pitcher -- listed or not -- needs TODAY's actual Baseball
    Savant ERA-xERA gap (fetch_savant.py) to clear DYNAMIC_GAP in the
    matching direction before anything fires: a big enough negative gap
    confirms a mirage (fade), a big enough positive gap confirms genuine
    quality (back). A pitcher can quietly stop being a mirage -- or a
    "legit arm" can quietly stop pitching well -- for weeks before anyone
    hand-updates RULES.md; requiring today's number closes that gap. List
    membership still shows up in the reason text (a listed + live-confirmed
    read carries more weight than a first-time discovery -- see
    attach_stars) but it never bypasses the live check on its own anymore.

    On top of that, the picked team's bullpen + lineup (fetch_teamstats.py)
    must not BOTH point against them relative to the opponent -- see
    team_support_ok(). A great starter mismatch can still get erased by a
    bad bullpen or a lineup that can't cash in on it.

    When two independent reasons land on the SAME side of the same game
    (e.g. the home pitcher is confirmed to back AND the away pitcher is
    confirmed to fade -- both mean "bet home"), that's conviction, not two
    plays: merged into one row sized at conviction units instead of firing
    twice. Only genuinely opposing sides (the model disagreeing with
    itself) still get skipped as a conflict.
    """
    opens = opens or {}
    public = public or {}
    savant_stats = savant_stats or {}
    team_stats = team_stats or {}
    rows, meta = [], []
    for g in games:
        if not in_window(g, now):
            continue
        key = f"{fetch_odds._norm(g['away'])}@{fetch_odds._norm(g['home'])}"
        entries = odds.get((fetch_odds._norm(g["away"]), fetch_odds._norm(g["home"])), [])
        o = fetch_odds.closest(entries, g["start_utc"]) or {}
        candidates = []  # dicts: bet_side, bet_team, note, pitcher, dyn, listed -- collected
                          # before committing, so same-side conviction merges and
                          # opposing-side conflicts can both be resolved first

        for side, pk, team in (("away", g.get("away_prob"), g.get("away")),
                               ("home", g.get("home_prob"), g.get("home"))):
            if not pk:
                continue
            stat = dynamic_match(pk, savant_stats)
            if not stat or abs(stat["gap"]) < DYNAMIC_GAP:
                continue
            listed = _list_tag(pk)
            opp_side = "home" if side == "away" else "away"
            if stat["gap"] <= -DYNAMIC_GAP:          # confirmed mirage -> fade
                bet_side, bet_team = opp_side, g[opp_side]
                note = f"fade {_fmt(pk)}" + (", listed mirage" if listed == "mirage" else ", live gap")
            else:                                    # confirmed quality -> back
                bet_side, bet_team = side, team
                note = f"back {_fmt(pk)}" + (f", listed {listed}" if listed in ("legit", "reverse") else ", live gap")
            if not team_support_ok(bet_team, g[opp_side], team_stats):
                print(f"game_pk {g['game_pk']}: {bet_team} starter-gap edge vetoed -- "
                      f"bullpen AND lineup both favor {g[opp_side]}.")
                continue
            ml = o.get(f"{bet_side}_ml")
            if ml is None:
                continue
            candidates.append({"bet_side": bet_side, "bet_team": bet_team, "note": note,
                               "pitcher": _fmt(pk), "ml": ml, "dyn": stat, "listed": listed is not None})

        if not candidates:
            continue

        sides = {c["bet_side"] for c in candidates}
        if len(sides) > 1:
            # Both sides of the same game flagged -- the model disagrees with
            # itself, which is not a clean edge. Never fire two plays betting
            # against each other; pass the whole game instead of guessing.
            picks = ", ".join(f'{c["bet_team"]} ({c["note"]})' for c in candidates)
            print(f"Skipping game_pk {g['game_pk']} ({g['away']} @ {g['home']}): "
                  f"conflicting signals on both sides ({picks}) -- no clean edge, passing.")
            continue

        primary, extras = candidates[0], candidates[1:]
        bet_side, bet_team, ml = primary["bet_side"], primary["bet_team"], primary["ml"]
        conviction = len(candidates)
        notes = "; ".join(c["note"] for c in candidates)

        open_ml = opens.get(key, {}).get(f"{bet_side}_ml", ml)   # fall back to current
        pub = (public.get(str(g["game_pk"])) or {}).get(bet_side)  # optional
        row = {"sport": "mlb", "selection": f"{bet_team} ML ({notes})",
               "pitcher": primary["pitcher"], "odds": ml, "market": "ml",
               "venue": "coors" if "Coors" in g["venue"] else g["venue"],
               "conviction": conviction, "extra_notes": [e["note"] for e in extras],
               "dyn_gap": primary["dyn"]["gap"], "dyn_era": primary["dyn"]["era"],
               "dyn_xera": primary["dyn"]["xera"], "listed": primary["listed"]}
        m = {"game_pk": g["game_pk"], "selection": f"{bet_team} ML",
             "bet_side": bet_side, "bet_team": bet_team,
             "start_utc": g["start_utc"],
             "open_ml": open_ml, "cur_ml": ml, "public_pct": pub,
             "conviction": conviction}
        rows.append(row)
        meta.append(m)
    return rows, meta


def record_opens(games, odds, opens):
    """First line seen for each game today becomes the 'open'. Date-aware."""
    if opens.get("date") != _today():
        opens = {"date": _today(), "lines": {}}
    lines = opens["lines"]
    for g in games:
        key = f"{fetch_odds._norm(g['away'])}@{fetch_odds._norm(g['home'])}"
        entries = odds.get((fetch_odds._norm(g["away"]), fetch_odds._norm(g["home"])), [])
        o = fetch_odds.closest(entries, g["start_utc"]) or {}
        if key not in lines and (o.get("home_ml") is not None or o.get("away_ml") is not None):
            lines[key] = {"home_ml": o.get("home_ml"), "away_ml": o.get("away_ml")}
    return opens


def _fmt(full):
    """'Aaron Nola' -> 'A. Nola' to match list style; leave single-token names alone."""
    parts = full.split()
    return f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else full


def apply_conviction(slate, graded):
    """Multiply risk/to_win by conviction (see build_slate's same-side
    merge) and note the extra reason(s) so the notification explains why
    it's sized above 1 unit. Keeps model.py's staking math untouched --
    this only scales the 1-unit result it already returned.

    A 2-star pick is lower-confidence -- don't let it ride at the full 2x
    conviction size just because two independent reasons happened to agree;
    cap it at 1.5x instead. Requires stars to already be attached, so this
    must run after attach_stars()."""
    for p, row in zip(slate, graded):
        conviction = p.get("conviction", 1)
        if row["verdict"] != "PLAY" or conviction <= 1:
            continue
        effective = 1.5 if (conviction == 2 and row.get("stars") == 2) else conviction
        row["risk"] = round(row["risk"] * effective, 2)
        row["to_win"] = round(row["to_win"] * effective, 2)
        extra = p.get("extra_notes") or []
        if extra:
            row["reason"] += f"  ({effective}x conviction — also: {'; '.join(extra)})"
    return graded


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


PENDING_REVIEW_FILE = os.environ.get("PENDING_REVIEW_FILE", "pending_review.json")
REVIEW_HOLD_MINUTES = 60


def resolve_reviews(graded, meta, now=None):
    """REVIEW verdicts (RLM thinks the market opposes the play) are never
    sent directly -- fully automate the "is this actually worth sending"
    call instead of pushing that judgment onto the notification. Hold a
    REVIEW game quietly; if a later run clears it back to a clean PLAY
    within REVIEW_HOLD_MINUTES, it gets sent then like any other pick, same
    as usual. Still REVIEW (or its window closes) once that deadline
    passes -> drop it for good, never sent.

    Caveat worth knowing: a full scan only runs roughly every ~100 minutes
    (see market_hours_open's MIN_GAP_MINUTES -- a deliberate Odds API quota
    throttle), so in practice a held play gets exactly one more look before
    the 60-minute deadline is already behind it."""
    now = now or datetime.now(timezone.utc)
    pending = load_json(PENDING_REVIEW_FILE, {})
    seen_this_run = set()
    for row, m in zip(graded, meta):
        pk = str(m["game_pk"])
        if row["verdict"] == "REVIEW":
            seen_this_run.add(pk)
            if pk not in pending:
                pending[pk] = now.isoformat()
                print(f"Holding game_pk {pk} for review (first seen) -- not sending yet.")
                continue
            elapsed_min = (now - datetime.fromisoformat(pending[pk])).total_seconds() / 60.0
            if elapsed_min >= REVIEW_HOLD_MINUTES:
                print(f"game_pk {pk} still REVIEW after {elapsed_min:.0f}m -- dropping, never sending.")
                del pending[pk]
            else:
                print(f"game_pk {pk} still REVIEW ({elapsed_min:.0f}m elapsed) -- holding, not sending yet.")
        elif pk in pending:
            print(f"game_pk {pk} cleared to PLAY -- releasing from review hold.")
            del pending[pk]
    for pk in list(pending):  # safety-net cleanup for entries a game's own window outran
        if pk in seen_this_run:
            continue
        try:
            if (now - datetime.fromisoformat(pending[pk])).total_seconds() / 3600.0 >= 24:
                del pending[pk]
        except Exception:
            del pending[pk]
    save_json(PENDING_REVIEW_FILE, pending)


def attach_stars(slate, graded):
    """Attach a 1-5 star confidence rating to each graded row. Every pick
    now carries a live dyn_gap (see build_slate), so "is_dynamic" here means
    "not on a RULES.md list" specifically -- a listed pitcher whose current
    numbers ALSO confirm the read is a stronger signal (double-confirmed)
    than a pitcher discovered from live numbers alone, same distinction the
    star rubric drew before this pick, with dyn_gap read from the original
    slate row since model.run()'s output doesn't carry custom fields through
    (same reason the totals 'total' field needed meta), and the RLM tag
    apply_rlm() already attached."""
    for p, row in zip(slate, graded):
        is_dynamic = not p.get("listed", False)
        rlm_tag = (row.get("rlm") or {}).get("tag")
        row["stars"] = star_rating(is_dynamic=is_dynamic, dyn_gap=p.get("dyn_gap"), rlm_tag=rlm_tag)
    return graded


def _star_str(n):
    n = max(1, min(5, n or 3))
    return "★" * n + "☆" * (5 - n)


def _local_time(start_utc):
    """'2026-07-18T23:05:00Z' -> '7:05 PM ET'. Same conversion the dashboard
    uses -- included in every notification so two games between the same
    teams (a doubleheader) are never ambiguous about which one fired."""
    if not start_utc:
        return "time TBD"
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return et.strftime("%-I:%M %p ET")
    except Exception:
        return start_utc


def _pick_and_reason(row, m=None):
    """Split a graded row into (pick line, reason line) so callers can
    format each notification channel differently -- e.g. Discord bolds
    just the pick, ntfy stays plain text for both. Only ever called for a
    clean PLAY now -- REVIEW verdicts are held/dropped by resolve_reviews()
    and never reach here directly."""
    tag = ""
    if row.get("rlm"):
        tag = f"  [{row['rlm']['tag']} {row['rlm']['detail']}]"
    note = f"  {row.get('rlm_note','')}" if row.get("rlm_note") else ""
    when = f" — {_local_time(m['start_utc'])}" if m else ""
    pick = (f"PLAY: {row['sel']}{when} {row['odds']:+d} "
            f"(risk {row['risk']}u/win {row['to_win']}u){tag}  {_star_str(row.get('stars'))}")
    reason = f"{row['reason']}{note}"
    return pick, reason


def new_plays(graded, meta, sent):
    """Return fresh PLAY rows whose game_pk hasn't been notified yet. REVIEW
    verdicts are handled separately by resolve_reviews() -- held, not sent
    directly, and only ever show up here if a later run clears them to a
    clean PLAY."""
    fresh = []
    for row, m in zip(graded, meta):
        if row["verdict"] == "PLAY" and str(m["game_pk"]) not in sent:
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
    if not market_hours_open():
        print("Not within grace of a scan checkpoint — skipping, no API calls made.")
        return
    record_run()

    games = fetch_mlb.todays_games()
    odds = fetch_odds.mlb_moneylines()

    opens = record_opens(games, odds, load_json(OPENS_FILE, {}))   # snapshot opening lines
    save_json(OPENS_FILE, opens)
    public = load_json(PUBLIC_FILE, {})                            # optional bet% you supply

    try:
        savant_stats = fetch_savant.season_pitcher_stats()         # dynamic ERA/xERA layer
    except Exception as e:
        print(f"Savant fetch failed, skipping dynamic layer this run: {e}")
        savant_stats = {}

    try:
        team_stats = fetch_teamstats.all_team_stats()              # bullpen/lineup confirmation
    except Exception as e:
        print(f"Team-stats fetch failed, skipping supporting-cast check this run: {e}")
        team_stats = {}

    slate, meta = build_slate(games, odds, opens["lines"], public,
                               savant_stats=savant_stats, team_stats=team_stats)
    graded, must_parlay = run(slate)
    graded = apply_rlm(graded, meta)                              # market overlay
    resolve_reviews(graded, meta)                                 # hold/drop REVIEW verdicts -- never sent directly
    graded = attach_stars(slate, graded)                          # 1-5 confidence rating
    graded = apply_conviction(slate, graded)                      # merge same-side conviction picks (star-aware sizing)
    sent = load_state()
    fresh = new_plays(graded, meta, sent)

    if not fresh:
        print("No new qualifying plays this scan.")
        return

    lines, discord_lines = [], []
    for row, m in fresh:
        pick, reason = _pick_and_reason(row, m)
        lines.append(f"{pick}\n   {reason}")
        discord_lines.append(f"**{pick}**\n{reason}")
        sent.add(str(m["game_pk"]))
    if len(must_parlay) >= 2:
        tail = "🔗 Cap rule: parlay the -150+ favs together."
        lines.append(tail); discord_lines.append(tail)
    elif len(must_parlay) == 1:
        tail = "⚠️ Lone -150+ fav — parlay or log override."
        lines.append(tail); discord_lines.append(tail)

    body = "\n".join(lines)
    title = f"⚾ {len(fresh)} play(s) — starts within {int(LEAD_HOURS)}h"
    notify.push(title, body)
    if discord_notify.push(title, "\n".join(discord_lines)):
        discord_notify.record_sent(str(m["game_pk"]) for _, m in fresh)
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
            "stars": row.get("stars", 3),
            "graded": False, "result": None,
        })
    save_json(path, card)


if __name__ == "__main__":
    main()
