import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any

from fastmcp import Context, FastMCP

from ..tools import API_ERROR_TEXT

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 30
USER_AGENT = "dsmora-python-hello-2/0.1"
WEATHER_CODES = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna ligera",
    53: "llovizna moderada",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia moderada",
    65: "lluvia intensa",
    71: "nevada ligera",
    73: "nevada moderada",
    75: "nevada intensa",
    80: "chubascos ligeros",
    81: "chubascos moderados",
    82: "chubascos violentos",
    95: "tormenta",
    96: "tormenta con granizo ligero",
    99: "tormenta con granizo intenso",
}


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_current_weather(city: str) -> str:
    city = city.strip()
    if not city:
        return "Error: la ciudad no puede estar vacía."

    try:
        geo = _get_json(
            GEOCODING_URL,
            {"name": city, "count": 1, "language": "es", "format": "json"},
        )
        places = geo.get("results")
        if not places:
            return f"Error: no se encontró la ciudad '{city}'."

        place = places[0]
        forecast = _get_json(
            FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,wind_speed_10m,weather_code",
            },
        )
        current = forecast["current"]
        units = forecast["current_units"]
    except Exception:
        return API_ERROR_TEXT

    condition = WEATHER_CODES.get(current["weather_code"], "estado desconocido")
    return (
        f"{place['name']} ({place.get('country', 'país desconocido')}): "
        f"{current['temperature_2m']} {units['temperature_2m']}, "
        f"viento de {current['wind_speed_10m']} {units['wind_speed_10m']}, {condition}."
    )

mcp = FastMCP("weather")


@mcp.tool()
async def get_weather(city: str, ctx: Context) -> str:
    """Solicita consentimiento explícito antes de consultar el tiempo actual."""
    try:
        consent = await ctx.elicit(
            f"¿Autorizas consultar el tiempo de {city} mediante Open-Meteo?",
            response_type=bool,
        )
    except Exception:
        return "No se consultó el tiempo: se requiere tu consentimiento explícito."

    if getattr(consent, "action", None) != "accept" or getattr(consent, "data", None) is not True:
        return "No se consultó el tiempo: se requiere tu consentimiento explícito."

    return await asyncio.to_thread(_get_current_weather, city)


if __name__ == "__main__":
    mcp.run(transport="stdio")