"""
stadiums_football.py — static NFL stadium reference (lat/lon + roof type), keyed by the
standard team abbreviation nflverse/nfl_data_py uses (matches fetch_nfl.py's team codes
directly, no name-normalization needed).

ROOF: "outdoor" | "dome" | "retractable". Dome/retractable games get no weather edge
(see RULES_FOOTBALL.md category B) regardless of the day's actual forecast.

LAT/LON: for the NWS weather lookup in fetch_weather.py (reused unmodified from the MLB
build). Like ballparks.py's PARK_FACTOR, this drifts slowly (stadium moves/renames) —
worth a once-a-season sanity check, not a live-fetched value.

CFB venues are NOT listed here — CollegeFootballData's /venues endpoint (cached in
fetch_cfb.py) covers all ~130 FBS venues for free, which beats hand-typing them.
"""

NFL_STADIUMS = {
    "ARI": {"venue": "State Farm Stadium",            "lat": 33.5276, "lon": -112.2626, "roof": "retractable"},
    "ATL": {"venue": "Mercedes-Benz Stadium",          "lat": 33.7554, "lon": -84.4008,  "roof": "retractable"},
    "BAL": {"venue": "M&T Bank Stadium",               "lat": 39.2780, "lon": -76.6227,  "roof": "outdoor"},
    "BUF": {"venue": "Highmark Stadium",                "lat": 42.7738, "lon": -78.7870,  "roof": "outdoor"},
    "CAR": {"venue": "Bank of America Stadium",         "lat": 35.2258, "lon": -80.8528,  "roof": "outdoor"},
    "CHI": {"venue": "Soldier Field",                   "lat": 41.8623, "lon": -87.6167,  "roof": "outdoor"},
    "CIN": {"venue": "Paycor Stadium",                  "lat": 39.0954, "lon": -84.5160,  "roof": "outdoor"},
    "CLE": {"venue": "Huntington Bank Field",           "lat": 41.5061, "lon": -81.6995,  "roof": "outdoor"},
    "DAL": {"venue": "AT&T Stadium",                    "lat": 32.7473, "lon": -97.0945,  "roof": "retractable"},
    "DEN": {"venue": "Empower Field at Mile High",      "lat": 39.7439, "lon": -105.0201, "roof": "outdoor"},
    "DET": {"venue": "Ford Field",                      "lat": 42.3400, "lon": -83.0456,  "roof": "dome"},
    "GB":  {"venue": "Lambeau Field",                   "lat": 44.5013, "lon": -88.0622,  "roof": "outdoor"},
    "HOU": {"venue": "NRG Stadium",                     "lat": 29.6847, "lon": -95.4107,  "roof": "retractable"},
    "IND": {"venue": "Lucas Oil Stadium",                "lat": 39.7601, "lon": -86.1639,  "roof": "retractable"},
    "JAX": {"venue": "EverBank Stadium",                 "lat": 30.3239, "lon": -81.6373,  "roof": "outdoor"},
    "KC":  {"venue": "GEHA Field at Arrowhead Stadium", "lat": 39.0489, "lon": -94.4839,  "roof": "outdoor"},
    "LV":  {"venue": "Allegiant Stadium",                "lat": 36.0909, "lon": -115.1833, "roof": "dome"},
    "LAC": {"venue": "SoFi Stadium",                     "lat": 33.9535, "lon": -118.3392, "roof": "dome"},
    "LA":  {"venue": "SoFi Stadium",                     "lat": 33.9535, "lon": -118.3392, "roof": "dome"},
    "MIA": {"venue": "Hard Rock Stadium",                "lat": 25.9580, "lon": -80.2389,  "roof": "outdoor"},
    "MIN": {"venue": "U.S. Bank Stadium",                "lat": 44.9735, "lon": -93.2575,  "roof": "dome"},
    "NE":  {"venue": "Gillette Stadium",                 "lat": 42.0909, "lon": -71.2643,  "roof": "outdoor"},
    "NO":  {"venue": "Caesars Superdome",                "lat": 29.9511, "lon": -90.0812,  "roof": "dome"},
    "NYG": {"venue": "MetLife Stadium",                  "lat": 40.8135, "lon": -74.0745,  "roof": "outdoor"},
    "NYJ": {"venue": "MetLife Stadium",                  "lat": 40.8135, "lon": -74.0745,  "roof": "outdoor"},
    "PHI": {"venue": "Lincoln Financial Field",          "lat": 39.9008, "lon": -75.1675,  "roof": "outdoor"},
    "PIT": {"venue": "Acrisure Stadium",                 "lat": 40.4468, "lon": -80.0158,  "roof": "outdoor"},
    "SF":  {"venue": "Levi's Stadium",                   "lat": 37.4032, "lon": -121.9698, "roof": "outdoor"},
    "SEA": {"venue": "Lumen Field",                      "lat": 47.5952, "lon": -122.3316, "roof": "outdoor"},
    "TB":  {"venue": "Raymond James Stadium",            "lat": 27.9759, "lon": -82.5033,  "roof": "outdoor"},
    "TEN": {"venue": "Nissan Stadium",                   "lat": 36.1665, "lon": -86.7713,  "roof": "outdoor"},
    "WAS": {"venue": "Northwest Stadium",                "lat": 38.9078, "lon": -76.8645,  "roof": "outdoor"},
}


def for_team(abbr):
    """Exact-match lookup by nflverse team abbreviation; None if not found."""
    return NFL_STADIUMS.get((abbr or "").upper())
