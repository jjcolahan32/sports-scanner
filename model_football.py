"""
model_football.py — NFL/CFB rules engine. RULES_FOOTBALL.md is the source of truth for
the logic; this is its implementation. Phase 1: spreads, totals, moneylines only (see
RULES_FOOTBALL.md Section 2G for the anytime-TD prop spec, not built yet).

Core philosophy (RULES_FOOTBALL.md Section 1): a pick is CONFIRMED only when 2+
independent signal categories stack in the SAME direction. Exactly one category firing
is a NOTE (never staked). Conflicting categories (roughly equal weight on both sides) is
a PASS, not a guess -- same "never fire two plays betting against each other" rule
scan.py's build_slate() already applies for MLB.

Unlike the MLB model (which grades an already-fully-formed candidate bound to one
pitcher/side), football's "which side do the signals favor" decision is genuinely part
of the category-stacking logic itself, so it lives here rather than in the scan layer --
callers (scan_nfl.py/scan_cfb.py) hand in BOTH teams' signals for a game and get back a
verdict + the side/total lean the categories point to; they attach the matching odds and
apply staking (american_to_stake/cap_rule, imported from model.py -- pure odds math, not
baseball-specific, reused unmodified) afterward.

Candidate dict shape (built by the scan layer from fetch_nfl.py/fetch_cfb.py/
fetch_weather.py/fetch_odds_football.py -- any field may be None, meaning "no data this
run", never a hard requirement):
  sport            "nfl" | "cfb"
  home, away       team codes/names
  home_rating, away_rating       power rating, higher = better (NFL: season point-diff
                                  proxy from fetch_nfl.team_power_ratings; CFB: SP+
                                  overall rating from fetch_cfb.team_ratings -- already
                                  conference-adjusted, see RULES_FOOTBALL.md 2E)
  home_injury_burden, away_injury_burden   float, see injury_burden() below
  home_rest, away_rest           days of rest (int), from games.csv/CFBD
  div_game                       bool -- divisional/conference-familiar matchup
  roof                           "outdoor" | "dome" | "retractable" (this game's stadium)
  away_team_is_dome_team         bool -- the traveling team's OWN home venue is domed
                                  (RULES_FOOTBALL.md 2B: hurts more on the road outdoors)
  wind_mph, temp_f, precip       weather at kickoff (precip: bool); None if dome/retractable
                                  or forecast unavailable (NWS only covers ~7 days out)
"""
import json
# Staking (model.american_to_stake/cap_rule -- pure odds math, reused unmodified) is
# applied by the scan layer once it knows the real price for the side/total this module
# picked, not here -- see scan_nfl.py/scan_cfb.py's grade_game().

WIND_THRESHOLD_MPH = 15
COLD_THRESHOLD_F = 32
REST_EDGE_DAYS = 3          # rest-day gap that counts as a situational edge
INJURY_BURDEN_EDGE = 1.5    # burden-differential (see injury_burden()) that counts as a signal
RATING_EDGE_NFL = 3.0       # point-differential-proxy gap that counts as a mismatch (NFL)
RATING_EDGE_CFB = 6.0       # SP+ rating-point gap that counts as a mismatch (CFB, wider scale)

# Injury burden weights by position group -- QB dominates (RULES_FOOTBALL.md 2A: "single
# biggest line-mover"); no snap-count-confirmed "starter" flag in phase 1, so every other
# position is weighted flat within its group rather than pretending to know who WR1/RB1
# is (that distinction is a props-phase data need -- see fetch_props.py in the doc's
# module map, not built yet).
POSITION_WEIGHT = {
    "QB": 3.0,
    "OL": 1.25, "T": 1.25, "G": 1.25, "C": 1.25,
    "WR": 1.0, "RB": 1.0, "TE": 0.75,
    "DE": 0.75, "DT": 0.75, "EDGE": 0.75, "LB": 0.6,
    "CB": 0.75, "S": 0.6,
}
STATUS_WEIGHT = {"Out": 1.0, "Doubtful": 0.75, "Questionable": 0.35}


def injury_burden(team_injuries):
    """Sum of position-weight x status-weight across a team's injury report -- the
    RULES_FOOTBALL.md 2A composite (QB status heaviest, OL/skill next, trend-aware via
    the practice_trend downgrade below). team_injuries: {player_name: {status,
    practice_trend, position}} from fetch_nfl.injuries() (or {} for CFB/no data)."""
    burden = 0.0
    for info in (team_injuries or {}).values():
        status_w = STATUS_WEIGHT.get(info.get("status"), 0.0)
        if status_w == 0.0:
            continue
        # "a questionable that practiced full Friday is often noise" (RULES_FOOTBALL.md
        # 2A) -- the trend, not the tag, is the real signal.
        trend = info.get("practice_trend") or ""
        if info.get("status") == "Questionable" and trend.endswith("Full Participation in Practice"):
            continue
        pos_w = POSITION_WEIGHT.get((info.get("position") or "").upper(), 0.4)
        burden += status_w * pos_w
    return round(burden, 2)


def _side(diff, edge, favors_home_note, favors_away_note):
    """diff = home_value - away_value. Returns (direction, note) where +1 favors home,
    -1 favors away, 0 = no signal (|diff| below the edge threshold, or either side
    missing)."""
    if diff is None:
        return 0, None
    if diff >= edge:
        return 1, favors_home_note
    if diff <= -edge:
        return -1, favors_away_note
    return 0, None


def cat_injury(p):
    """Category A. Heavier injury burden on one team favors their opponent."""
    hb, ab = p.get("home_injury_burden"), p.get("away_injury_burden")
    if hb is None or ab is None:
        return 0, None
    diff = ab - hb   # away hurt more -> favors home
    return _side(diff, INJURY_BURDEN_EDGE,
                 f"away injury burden {ab:.1f} vs home {hb:.1f}",
                 f"home injury burden {hb:.1f} vs away {ab:.1f}")


def cat_mismatch(p):
    """Category D. Power-rating differential (NFL: season point-diff proxy; CFB: SP+)."""
    hr, ar = p.get("home_rating"), p.get("away_rating")
    if hr is None or ar is None:
        return 0, None
    edge = RATING_EDGE_CFB if p.get("sport") == "cfb" else RATING_EDGE_NFL
    diff = hr - ar
    return _side(diff, edge,
                 f"rating edge home {hr:.1f} vs away {ar:.1f}",
                 f"rating edge away {ar:.1f} vs home {hr:.1f}")


def cat_situational(p):
    """Category E. Rest differential -- short week / extra rest off a bye. Divisional
    familiarity is noted but not directional for spread/ML (RULES_FOOTBALL.md only ties
    it to unders, see cat_weather's div_game bump for totals)."""
    hr, ar = p.get("home_rest"), p.get("away_rest")
    if hr is None or ar is None:
        return 0, None
    diff = hr - ar
    return _side(diff, REST_EDGE_DAYS,
                 f"home rest edge ({hr}d vs {ar}d)",
                 f"away rest edge ({ar}d vs {hr}d)")


def cat_weather_total(p):
    """Category B, totals framing. Dome/retractable-roof games get no weather edge at
    all (RULES_FOOTBALL.md 2B) -- don't manufacture one."""
    if p.get("roof") != "outdoor":
        return 0, None
    wind, temp, precip = p.get("wind_mph"), p.get("temp_f"), p.get("precip")
    if wind is not None and wind >= WIND_THRESHOLD_MPH:
        return -1, f"wind {wind:.0f}mph"
    if precip:
        return -1, "precipitation"
    if temp is not None and temp <= COLD_THRESHOLD_F:
        return -1, f"cold {temp:.0f}F"
    return 0, None


def cat_dome_travel_total(p):
    """Category C for totals -- the doc's own worked example of the run/pass-fit
    connective layer: a dome team on the road in real outdoor weather is hurt MORE than
    the raw weather number alone implies (RULES_FOOTBALL.md 2B). Only fires when
    cat_weather_total already fired AND the traveling team is a dome team -- a genuine
    reinforcement, not a restatement of the same data point."""
    w_dir, _ = cat_weather_total(p)
    if w_dir >= 0 or not p.get("away_team_is_dome_team"):
        return 0, None
    return -1, "dome team traveling into bad outdoor weather"


def cat_injury_total(p):
    """Category A, totals framing -- either team's offense being degraded leans UNDER
    (cumulative, not offsetting: two hurt offenses is a stronger under lean than one)."""
    hb, ab = p.get("home_injury_burden") or 0.0, p.get("away_injury_burden") or 0.0
    if p.get("home_injury_burden") is None and p.get("away_injury_burden") is None:
        return 0, None
    total = hb + ab
    if total >= INJURY_BURDEN_EDGE:
        return -1, f"combined offensive injury burden {total:.1f}"
    return 0, None


def cat_pace_total(p):
    """Category D, totals framing -- both teams rating above/below the field suggests a
    high/low-scoring environment. Crude (no explicit pace/efficiency split available in
    phase 1), so only fires when BOTH teams agree, not just the average."""
    hr, ar = p.get("home_rating"), p.get("away_rating")
    if hr is None or ar is None:
        return 0, None
    league_avg = p.get("league_avg_rating", 0.0)
    if hr > league_avg and ar > league_avg:
        return 1, "both teams rate above league-average"
    if hr < league_avg and ar < league_avg:
        return -1, "both teams rate below league-average"
    return 0, None


def _stack(cats):
    """cats: list of (direction, category_name, note). Returns (verdict_pre_rlm, side,
    fired) where side is +1/-1 (home/over vs away/under), fired is the list of
    (category_name, note) that agreed with the winning side. verdict is one of
    CONFIRMED/NOTE/PASS -- RLM overlay (applied by the scan layer, see rlm.py) can still
    move CONFIRMED->LEAN or NOTE->CONFIRMED afterward."""
    pos = [(name, note) for d, name, note in cats if d > 0]
    neg = [(name, note) for d, name, note in cats if d < 0]
    if len(pos) >= 2 and len(pos) > len(neg):
        return "CONFIRMED", 1, pos
    if len(neg) >= 2 and len(neg) > len(pos):
        return "CONFIRMED", -1, neg
    if len(pos) == 1 and not neg:
        return "NOTE", 1, pos
    if len(neg) == 1 and not pos:
        return "NOTE", -1, neg
    if len(pos) == len(neg) and (pos or neg):
        return "PASS", 0, []   # conflicting signals, equal weight -- no clean edge
    # Unequal but both >=1 and neither reaches 2+ net (e.g. 1 vs 0 already handled above;
    # this covers e.g. 2-vs-1 where the majority already returned above, so remaining
    # case is a genuine tie/near-tie fallback)
    winner = pos if len(pos) > len(neg) else neg
    if len(winner) >= 2:
        return "CONFIRMED", (1 if winner is pos else -1), winner
    return "PASS", 0, []


def grade_spread(p):
    return _grade_side(p, "spread")


def grade_ml(p):
    return _grade_side(p, "moneyline")


def _grade_side(p, market_label):
    raw = [("injury", cat_injury(p)), ("mismatch", cat_mismatch(p)), ("situational", cat_situational(p))]
    cats = [(d, name, note) for name, (d, note) in raw if d != 0]
    verdict, side, fired = _stack(cats)
    home, away = p.get("home"), p.get("away")
    if side == 0:
        reason = "Conflicting categories, no clean edge" if cats else "No categories fired"
        return {"verdict": verdict, "side": None, "market": market_label, "reason": reason}
    pick_team = home if side > 0 else away
    reason = f"{pick_team} {market_label}: " + "; ".join(f"{n} ({note})" for n, note in fired)
    return {"verdict": verdict, "side": "home" if side > 0 else "away",
            "pick_team": pick_team, "market": market_label, "reason": reason,
            "categories": [n for n, _ in fired]}


def grade_total(p):
    cats_raw = [cat_weather_total(p), cat_dome_travel_total(p), cat_injury_total(p), cat_pace_total(p)]
    names = ["weather", "dome-travel", "injury", "pace"]
    cats = [(d, n, note) for (d, note), n in zip(cats_raw, names) if d != 0]
    verdict, side, fired = _stack(cats)
    if side == 0:
        reason = "Conflicting categories, no clean edge" if cats else "No categories fired"
        return {"verdict": verdict, "side": None, "market": "total", "reason": reason}
    label = "Over" if side > 0 else "Under"
    reason = f"{label}: " + "; ".join(f"{n} ({note})" for n, note in fired)
    return {"verdict": verdict, "side": "over" if side > 0 else "under",
            "market": "total", "reason": reason, "categories": [n for n, _ in fired]}


def verdict_adjust_football(verdict, rlm_tag):
    """RLM/steam overlay (RULES_FOOTBALL.md Section 3): market agreement can itself be
    one of the 2+ stacked categories (promotes a lone-category NOTE to CONFIRMED);
    market disagreement doesn't kill a CONFIRMED pick outright but downgrades it to LEAN
    until the conflict resolves. Distinct from the MLB model's PLAY->REVIEW->hold/drop
    state machine (rlm.verdict_adjust) -- this is the simpler tri-state the doc actually
    specifies, applied on top of the SAME rlm.py tag (rlm.py itself is unmodified,
    sport-agnostic odds math)."""
    agree = rlm_tag in ("RLM-FOR", "STEAM-FOR")
    conflict = rlm_tag in ("RLM-AGAINST", "STEAM-AGAINST")
    if verdict == "CONFIRMED" and conflict:
        return "LEAN", "market opposing the pick — downgraded from CONFIRMED"
    if verdict == "NOTE" and agree:
        return "CONFIRMED", "market agreement promoted a lone category to CONFIRMED"
    return verdict, ""


GRADERS = {"spread": grade_spread, "total": grade_total, "ml": grade_ml}


def run(candidates):
    """candidates: list of (market, p) pairs -- callers grade each market independently
    per game (RULES_FOOTBALL.md Section 3: a spread edge doesn't imply a total edge)."""
    return [GRADERS[market](p) for market, p in candidates]


if __name__ == "__main__":
    # Pure-function smoke test, no network -- see selftest_football.py for the full suite.
    demo = {
        "sport": "nfl", "home": "KC", "away": "DEN",
        "home_injury_burden": 0.0, "away_injury_burden": 3.0,
        "home_rating": 6.0, "away_rating": -2.0,
        "home_rest": 7, "away_rest": 7,
        "roof": "outdoor", "away_team_is_dome_team": False,
        "wind_mph": 22, "temp_f": 28, "precip": False,
    }
    print(json.dumps(grade_spread(demo), indent=2))
    print(json.dumps(grade_total(demo), indent=2))
    print(json.dumps(grade_ml(demo), indent=2))
