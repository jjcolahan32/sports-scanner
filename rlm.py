"""
rlm.py — reverse-line-movement + steam overlay.

Fold market signal onto a fundamentals pick WITHOUT overriding it.
Two inputs:
  - line movement (open -> current) : always available (we snapshot it)
  - public ticket % on the bet side : OPTIONAL (no free API; you supply it)

Output tag on YOUR model's chosen side:
  RLM-FOR       public is light on your side but the price shortened toward it -> sharps agree
  RLM-AGAINST   public is heavy on your side but the price drifted off it      -> sharps disagree (CAUTION)
  STEAM-FOR     big move toward your side, no bet% available
  STEAM-AGAINST big move off your side, no bet% available
  NEUTRAL       no meaningful move / signal

Line movement is measured in implied-probability points so favorites and dogs
are on the same scale (a "+2%" shift means the side shortened by 2 prob points).
"""


def implied_prob(american):
    a = float(american)
    return (-a) / (-a + 100) if a < 0 else 100 / (a + 100)


def line_shift(open_ml, cur_ml):
    """Signed prob-point move for THIS side. + = shortened toward it, - = drifted off it."""
    return round(implied_prob(cur_ml) - implied_prob(open_ml), 4)


def evaluate(open_ml, cur_ml, public_pct_on_bet_side=None,
             steam=0.03, rlm_move=0.02, public_hi=0.60):
    """Return {tag, shift, detail, public_pct} for the side your model wants to bet."""
    shift = line_shift(open_ml, cur_ml)
    tag = "NEUTRAL"

    # Movement-only layer (no bet% needed)
    if shift >= steam:
        tag = "STEAM-FOR"
    elif shift <= -steam:
        tag = "STEAM-AGAINST"

    # True-RLM overlay (needs public ticket %)
    if public_pct_on_bet_side is not None:
        p = float(public_pct_on_bet_side)
        if p <= (1 - public_hi) and shift >= rlm_move:      # light public, price shortened -> sharps with you
            tag = "RLM-FOR"
        elif p >= public_hi and shift <= -rlm_move:         # heavy public, price drifted -> sharps against you
            tag = "RLM-AGAINST"

    detail = f"{_c(open_ml)}→{_c(cur_ml)} ({shift:+.0%})"
    if public_pct_on_bet_side is not None:
        detail += f", public {float(public_pct_on_bet_side):.0%}"
    return {"tag": tag, "shift": shift, "detail": detail,
            "public_pct": public_pct_on_bet_side}


def verdict_adjust(model_verdict, rlm_tag):
    """How the overlay modifies a model PLAY. Advisory, never silent-drops.
       CONFLICT downgrades PLAY -> REVIEW so you eyeball it; confirmation flags it hot."""
    if model_verdict != "PLAY":
        return model_verdict, ""
    if rlm_tag in ("RLM-AGAINST", "STEAM-AGAINST"):
        return "REVIEW", "⚠ market opposing your side — consider pass/reduce"
    if rlm_tag in ("RLM-FOR", "STEAM-FOR"):
        return "PLAY", "✅ sharp/market confirmation"
    return "PLAY", ""


def _c(ml):
    ml = int(ml)
    return f"{ml:+d}"


if __name__ == "__main__":
    # quick self-check
    print(evaluate(-140, -160))                      # shortened toward -> STEAM-FOR
    print(evaluate(-140, -120))                      # drifted off   -> STEAM-AGAINST
    print(evaluate(150, 130, public_pct_on_bet_side=0.25))  # light public, shortened -> RLM-FOR
    print(evaluate(-140, -120, public_pct_on_bet_side=0.72)) # heavy public, drifted  -> RLM-AGAINST
