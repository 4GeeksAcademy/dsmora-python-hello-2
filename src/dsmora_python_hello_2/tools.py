import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10

# Códigos WMO usados por Open-Meteo.
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


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., str]

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def run(self, arguments: dict[str, Any]) -> str:
        return self.function(**arguments)


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_wheater(city: str) -> str:
    """Devuelve el tiempo actual de una ciudad."""
    city = city.strip()
    if not city:
        return "Error: la ciudad no puede estar vacía."

    try:
        geo = _get_json(GEOCODING_URL, {"name": city, "count": 1, "language": "es", "format": "json"})
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
    except (OSError, ValueError, KeyError) as error:
        return f"Error al consultar el tiempo: {error}"

    condition = WEATHER_CODES.get(current["weather_code"], "estado desconocido")
    return (
        f"{place['name']} ({place.get('country', 'país desconocido')}): "
        f"{current['temperature_2m']} {units['temperature_2m']}, "
        f"viento de {current['wind_speed_10m']} {units['wind_speed_10m']}, {condition}."
    )


WEATHER_TOOL = Tool(
    name="get_wheater",
    description="Obtiene el tiempo actual de una ciudad.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Nombre de la ciudad, por ejemplo Madrid"},
        },
        "required": ["city"],
    },
    function=get_wheater,
)
