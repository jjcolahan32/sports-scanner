"""
Unified betting model — rules engine.
Single source of truth for the LOGIC lives here + RULES.md.

Input : a slate (list of candidate plays) as JSON — see slate.example.json
Output: graded card (PLAY / PASS + reason + stake), with cap-rule parlay grouping.

Usage:
    python model.py slate.example.json
"""
import json, sys

# ---- EDITABLE LISTS (keep in sync with RULES.md) -------------------------
LEGIT_ARMS = {
    "misiorowski","schlittler","c. sanchez","c. sánchez","sale","skenes","wheeler",
    "h. brown","ryan","rasmussen","mize","miller","cease","harrison","messick",
    "mcclanahan","ashcraft","n. martinez","henderson","detmers","roupp","luzardo","woodruff",
}
MIRAGES = {
    "s. gray","e. rodriguez","e. rodríguez","t. melton","arrighetti","sugano",
    "wrobleski","wacha","c. scott",
}
REVERSE_MIRAGES = {"a. nola","nola"}
RETIREMENT_PROFILE = {"dimitrov","djokovic"}
# --------------------------------------------------------------------------


def american_to_stake(odds):
    """Return (risk, to_win) in units per staking rules for a 1u target/flat dog."""
    if odds > 0:                       # underdog: risk flat 1u
        return 1.00, round(odds / 100, 2)
    else:                              # favorite: risk to win 1u
        return round(abs(odds) / 100, 2), 1.00


def cap_rule(odds):
    """Return one of: 'single_ok', 'must_parlay', 'dog'."""
    if odds > 0:
        return "dog"
    return "single_ok" if odds >= -150 else "must_parlay"


def _last_name(name):
    return name.strip().lower().split()[-1] if name.strip() else ""


def _matches_list(name, vetted_set):
    """Match by last-name token so 'J. Luzardo', 'Jesus Luzardo', and 'luzardo'
    all resolve to the same vetted entry regardless of which form is supplied."""
    last = _last_name(name)
    return bool(last) and any(v.split()[-1] == last for v in vetted_set)


def grade_mlb(p):
    name = p.get("pitcher", "").strip().lower()
    if p.get("venue", "").lower() == "coors" and p.get("market") == "total":
        return "PASS", "Coors total — automatic pass"
    if p.get("event_type") in ("allstar", "exhibition", "derby"):
        return "PASS", "Exhibition/All-Star — auto-pass"
    if p.get("market") == "total" and p.get("total", 99) <= 7.5:
        return "PASS", "Tight under behind ace keeps going over — take the side instead"
    if _matches_list(name, MIRAGES):
        return "PLAY", f"Fade mirage: {p['pitcher']} (ERA/xERA gap)"
    if _matches_list(name, REVERSE_MIRAGES):
        return "PLAY", f"Back reverse-mirage: {p['pitcher']} (ugly ERA understates)"
    if _matches_list(name, LEGIT_ARMS):
        return "PLAY", f"Back legit arm: {p['pitcher']}"
    return "PASS", "No pitcher edge in database"


def grade_tennis(p):
    if p.get("fitness_verified") is not True:
        return "PASS", "Fitness NOT verified — mandatory before every tennis play"
    if p.get("opponent", "").strip().lower() in RETIREMENT_PROFILE:
        return "PASS", f"Retirement-profile name-check: {p['opponent']}"
    if p.get("low_tier_post_wimbledon"):
        return "PASS", "Post-Wimbledon low-tier — auto-pass until hard court"
    if p.get("higher_ranked") and p.get("preferred_surface") and p.get("odds", -999) > 0:
        return "PLAY", "A-play: higher-ranked player, plus-money dog, preferred surface"
    return "PASS", "No A-play trigger"


def grade_soccer(p):
    if p.get("event_type") in ("consolation", "third_place"):
        return "PASS", "Consolation/3rd-place — low motivation, auto-pass"
    if p.get("quiet_favorite_lay"):
        return "PASS", "Quiet-favorite lay trap — pass"
    if p.get("keep_close_dog"):
        return "PLAY", "Keep-close resilient dog (+½/+1/pk)"
    return "PASS", "No keep-close dog edge"


def grade_golf(p):
    if p.get("leaderboard_inversion"):
        mult = " (emotional-distraction fade multiplier)" if p.get("emotional_distraction") else ""
        return "PLAY", f"Name-recognition trap — back the inverted dog{mult}"
    return "PASS", "No vetted golf read — pass book"


def grade_ufc(p):
    if p.get("clean_edge"):
        return "PLAY", "Genuinely clean skill edge"
    return "PASS", "UFC leakiest book — pass without clean edge"


GRADERS = {"mlb": grade_mlb, "tennis": grade_tennis, "soccer": grade_soccer,
           "golf": grade_golf, "ufc": grade_ufc}


def run(slate):
    out, must_parlay = [], []
    for p in slate:
        sport = p.get("sport", "").lower()
        verdict, reason = GRADERS.get(sport, lambda x: ("PASS", "Unknown sport"))(p)
        row = {"sport": sport, "sel": p.get("selection", "?"),
               "odds": p.get("odds"), "verdict": verdict, "reason": reason}
        if verdict == "PLAY" and p.get("odds") is not None:
            risk, win = american_to_stake(p["odds"])
            cap = cap_rule(p["odds"])
            row.update(risk=risk, to_win=win, cap=cap)
            if cap == "must_parlay":
                must_parlay.append(row)
        out.append(row)
    return out, must_parlay


def render(out, must_parlay):
    plays = [r for r in out if r["verdict"] == "PLAY"]
    print(f"\n=== CARD ({len(plays)} plays) ===")
    for r in out:
        tag = "✅" if r["verdict"] == "PLAY" else "⛔"
        line = f"{tag} [{r['sport'].upper()}] {r['sel']} {r.get('odds','')}"
        if r["verdict"] == "PLAY":
            line += f"  → risk {r['risk']}u / win {r['to_win']}u  [{r['cap']}]"
        print(f"{line}\n     {r['reason']}")
    if len(must_parlay) == 1:
        print("\n⚠️  CAP-RULE FLAG: one lone -150+ favorite. Cannot stand alone —")
        print("    pair it with another -150+ fav in an ML parlay, or log an override exception.")
    elif len(must_parlay) >= 2:
        legs = ", ".join(r["sel"] for r in must_parlay)
        print(f"\n🔗 CAP-RULE PARLAY: combine these -150+ favs → {legs}")
    if len(plays) > 5:
        print("\nℹ️  Card >5 plays — allowed only if every edge is genuine.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "slate.example.json"
    with open(path) as f:
        slate = json.load(f)
    render(*run(slate))
