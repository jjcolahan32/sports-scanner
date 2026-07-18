"""
ballparks.py — static per-stadium reference data for the totals model.

PARK_FACTOR: 3-year rolling runs park factor (100 = neutral MLB average park;
>100 = inflates run scoring, <100 = suppresses it). Widely-published
sabermetric reference numbers (FanGraphs/ESPN-style), not fetched live —
these drift slowly (humidor changes, fence moves) so they're worth a manual
review every season, same as the pitcher lists in model.py.

ORIENTATION_DEG: compass bearing from home plate through straightaway center
field (0=N, 90=E, 180=S, 270=W). Used to resolve "is the wind blowing out"
from a raw wind direction. Approximate — stadium-specific quirks (Coors'
altitude, Fenway's Monster, wind tunneling in enclosed parks) aren't modeled,
this is a first-order read only.

LAT/LON: for the NWS weather lookup in fetch_weather.py.
"""

BALLPARKS = {
    "Arizona Diamondbacks":  {"venue": "Chase Field",              "lat": 33.4455, "lon": -112.0667, "orientation_deg": 133, "park_factor": 98,  "roof": True},
    "Atlanta Braves":        {"venue": "Truist Park",              "lat": 33.8908, "lon": -84.4678,  "orientation_deg": 45,  "park_factor": 100, "roof": False},
    "Baltimore Orioles":     {"venue": "Camden Yards",             "lat": 39.2839, "lon": -76.6218,  "orientation_deg": 35,  "park_factor": 97,  "roof": False},
    "Boston Red Sox":        {"venue": "Fenway Park",               "lat": 42.3467, "lon": -71.0972,  "orientation_deg": 45,  "park_factor": 104, "roof": False},
    "Chicago Cubs":          {"venue": "Wrigley Field",             "lat": 41.9484, "lon": -87.6553,  "orientation_deg": 30,  "park_factor": 102, "roof": False},
    "Chicago White Sox":     {"venue": "Rate Field",                "lat": 41.8300, "lon": -87.6338,  "orientation_deg": 154, "park_factor": 99,  "roof": False},
    "Cincinnati Reds":       {"venue": "Great American Ball Park",  "lat": 39.0975, "lon": -84.5068,  "orientation_deg": 79,  "park_factor": 106, "roof": False},
    "Cleveland Guardians":   {"venue": "Progressive Field",         "lat": 41.4962, "lon": -81.6852,  "orientation_deg": 5,   "park_factor": 97,  "roof": False},
    "Colorado Rockies":      {"venue": "Coors Field",               "lat": 39.7559, "lon": -104.9942, "orientation_deg": 118, "park_factor": 114, "roof": False},
    "Detroit Tigers":        {"venue": "Comerica Park",             "lat": 42.3390, "lon": -83.0485,  "orientation_deg": 155, "park_factor": 96,  "roof": False},
    "Houston Astros":        {"venue": "Daikin Park",               "lat": 29.7573, "lon": -95.3555,  "orientation_deg": 55,  "park_factor": 99,  "roof": True},
    "Kansas City Royals":    {"venue": "Kauffman Stadium",          "lat": 39.0517, "lon": -94.4803,  "orientation_deg": 40,  "park_factor": 98,  "roof": False},
    "Los Angeles Angels":    {"venue": "Angel Stadium",             "lat": 33.8003, "lon": -117.8827, "orientation_deg": 15,  "park_factor": 97,  "roof": False},
    "Los Angeles Dodgers":   {"venue": "Dodger Stadium",            "lat": 34.0739, "lon": -118.2400, "orientation_deg": 25,  "park_factor": 96,  "roof": False},
    "Miami Marlins":         {"venue": "loanDepot park",            "lat": 25.7781, "lon": -80.2196,  "orientation_deg": 130, "park_factor": 95,  "roof": True},
    "Milwaukee Brewers":     {"venue": "American Family Field",     "lat": 43.0280, "lon": -87.9712,  "orientation_deg": 130, "park_factor": 100, "roof": True},
    "Minnesota Twins":       {"venue": "Target Field",              "lat": 44.9817, "lon": -93.2777,  "orientation_deg": 92,  "park_factor": 98,  "roof": False},
    "New York Mets":         {"venue": "Citi Field",                "lat": 40.7571, "lon": -73.8458,  "orientation_deg": 34,  "park_factor": 96,  "roof": False},
    "New York Yankees":      {"venue": "Yankee Stadium",            "lat": 40.8296, "lon": -73.9262,  "orientation_deg": 75,  "park_factor": 103, "roof": False},
    "Athletics":             {"venue": "Sutter Health Park",        "lat": 38.5802, "lon": -121.5142, "orientation_deg": 45,  "park_factor": 99,  "roof": False},
    "Philadelphia Phillies": {"venue": "Citizens Bank Park",        "lat": 39.9061, "lon": -75.1665,  "orientation_deg": 15,  "park_factor": 103, "roof": False},
    "Pittsburgh Pirates":    {"venue": "PNC Park",                  "lat": 40.4469, "lon": -80.0057,  "orientation_deg": 100, "park_factor": 95,  "roof": False},
    "San Diego Padres":      {"venue": "Petco Park",                "lat": 32.7073, "lon": -117.1566, "orientation_deg": 25,  "park_factor": 93,  "roof": False},
    "San Francisco Giants":  {"venue": "Oracle Park",               "lat": 37.7786, "lon": -122.3893, "orientation_deg": 92,  "park_factor": 92,  "roof": False},
    "Seattle Mariners":      {"venue": "T-Mobile Park",             "lat": 47.5914, "lon": -122.3325, "orientation_deg": 45,  "park_factor": 94,  "roof": True},
    "St. Louis Cardinals":   {"venue": "Busch Stadium",             "lat": 38.6226, "lon": -90.1928,  "orientation_deg": 60,  "park_factor": 97,  "roof": False},
    "Tampa Bay Rays":        {"venue": "Steinbrenner Field",        "lat": 27.9803, "lon": -82.5065,  "orientation_deg": 45,  "park_factor": 96,  "roof": False},
    "Texas Rangers":         {"venue": "Globe Life Field",          "lat": 32.7473, "lon": -97.0842,  "orientation_deg": 30,  "park_factor": 98,  "roof": True},
    "Toronto Blue Jays":     {"venue": "Rogers Centre",             "lat": 43.6414, "lon": -79.3894,  "orientation_deg": 75,  "park_factor": 101, "roof": True},
    "Washington Nationals":  {"venue": "Nationals Park",            "lat": 38.8730, "lon": -77.0074,  "orientation_deg": 43,  "park_factor": 98,  "roof": False},
}


def for_team(team_name):
    """Exact-match lookup by MLB StatsAPI team name; None if not found."""
    return BALLPARKS.get(team_name)
