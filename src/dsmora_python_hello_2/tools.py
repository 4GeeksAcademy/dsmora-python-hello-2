import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 30
USER_AGENT = "dsmora-python-hello-2/0.1"
# Texto neutro que sustituye cualquier fallo de una API externa; no expone detalles técnicos.
API_ERROR_TEXT = "No se pudo obtener la información en este momento."

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


def _open_json(request: urllib.request.Request) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}", headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    return _open_json(request)


def post_form_json(url: str, form: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, **(headers or {})},
        method="POST",
    )
    return _open_json(request)


def find_place(city: str) -> dict[str, Any] | None:
    """Devuelve la primera coincidencia de geocodificación para una ciudad."""
    geo = get_json(GEOCODING_URL, {"name": city, "count": 1, "language": "es", "format": "json"})
    places = geo.get("results")
    return places[0] if places else None


def get_wheater(city: str) -> str:
    """Devuelve el tiempo actual de una ciudad."""
    city = city.strip()
    if not city:
        return "Error: la ciudad no puede estar vacía."

    try:
        place = find_place(city)
        if place is None:
            return f"Error: no se encontró la ciudad '{city}'."

        forecast = get_json(
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
