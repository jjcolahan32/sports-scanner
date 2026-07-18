"""
fetch_weather.py — hourly forecast (temp, wind speed/direction) at a lat/lon,
for reading whether the wind favors an over or under at a given ballpark.

Source: National Weather Service API (api.weather.gov). Free, no key, US
government service — but it only covers US locations (fine, every MLB park
is domestic) and only forecasts a handful of days out, so this only means
anything once a game is within its forecast window.
"""
import json, urllib.request

POINTS = "https://api.weather.gov/points/{lat},{lon}"
UA = "card-scanner/1.0 (personal use, no contact configured)"

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def compass_to_deg(compass):
    """Convert a compass string like 'ENE' to degrees (0=N, 90=E). None if unknown."""
    try:
        return COMPASS.index(compass) * 22.5
    except ValueError:
        return None


def hourly_forecast(lat, lon):
    """Return the list of hourly forecast periods for a lat/lon (free NWS lookup)."""
    point = _get(POINTS.format(lat=lat, lon=lon))
    hourly_url = point["properties"]["forecastHourly"]
    data = _get(hourly_url)
    return data["properties"]["periods"]


def forecast_at(lat, lon, when_utc):
    """Return the single hourly period whose window covers when_utc (a
    timezone-aware datetime), or the closest one if none matches exactly.
    Returns {temp_f, wind_mph, wind_from_deg, short} or None if unavailable
    (e.g. game is further out than NWS forecasts, typically ~7 days)."""
    periods = hourly_forecast(lat, lon)
    best, best_diff = None, None
    for p in periods:
        start = p["startTime"]
        end = p.get("endTime", start)
        # startTime/endTime are ISO8601 with a numeric offset (NWS doesn't use "Z")
        from datetime import datetime
        p_start = datetime.fromisoformat(start)
        p_end = datetime.fromisoformat(end)
        if p_start <= when_utc < p_end:
            best = p
            break
        diff = abs((p_start - when_utc).total_seconds())
        if best_diff is None or diff < best_diff:
            best, best_diff = p, diff
    if best is None:
        return None
    wind_speed = best.get("windSpeed", "0 mph").split()[0]
    try:
        wind_mph = float(wind_speed)
    except ValueError:
        wind_mph = 0.0
    return {
        "temp_f": best.get("temperature"),
        "wind_mph": wind_mph,
        "wind_from_deg": compass_to_deg(best.get("windDirection", "")),
        "short": best.get("shortForecast"),
    }


def wind_out_component(wind_from_deg, wind_mph, park_orientation_deg):
    """Signed mph of wind blowing OUT toward center field (positive = out,
    negative = in). wind_from_deg is where the wind is COMING FROM (NWS
    convention), so the direction it's BLOWING TOWARD is +180 from that."""
    if wind_from_deg is None:
        return 0.0
    import math
    blowing_toward = (wind_from_deg + 180) % 360
    angle_diff = abs(blowing_toward - park_orientation_deg)
    angle_diff = min(angle_diff, 360 - angle_diff)
    return round(wind_mph * math.cos(math.radians(angle_diff)), 1)


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone
    lat, lon = (39.7559, -104.9942)  # Coors Field, as a live smoke test
    now = datetime.now(timezone.utc)
    fc = forecast_at(lat, lon, now)
    print("Coors Field forecast now:", fc)
    if fc:
        out_mph = wind_out_component(fc["wind_from_deg"], fc["wind_mph"], 118)
        print(f"Wind component toward CF (118deg): {out_mph:+.1f} mph "
              f"({'OUT' if out_mph > 0 else 'IN' if out_mph < 0 else 'neutral'})")
