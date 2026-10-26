import asyncio
import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ..tools import API_ERROR_TEXT
from .config import MCP_HOST, MCP_PORT
from .auth import SessionBindingMiddleware, bearer_middleware, principal
from ..security import database, key_client
from ..web_config import settings

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
            {"name": city, "count": 10, "language": "es", "format": "json", "countryCode": "MX"},
        )
        places = geo.get("results")
        if not places:
            return f"Error: no se encontró la ciudad '{city}'."

        place = next((item for item in places if item.get("country_code") == "MX"), None)
        if place is None:
            return "Error: solo se admiten localidades de Mexico."
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
    except (OSError, ValueError, KeyError, TypeError) as error:
        logging.getLogger(__name__).error("Fallo de clima: %s", type(error).__name__)
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
    principal("weather:read")
    if not city.strip() or len(city) > 120:
        raise ToolError("Indica una localidad de Mexico de hasta 120 caracteres.")
    if not await confirmed(ctx, f"Consultar el tiempo de {city} mediante Open-Meteo"):
        return "No se consultó el tiempo: se requiere tu consentimiento explícito."
    principal("weather:read")
    return await asyncio.to_thread(_get_current_weather, city)


async def confirmed(ctx: Context, action: str) -> bool:
    consent = await ctx.elicit(f"Confirma esta accion:\n{action}", response_type=bool)
    return getattr(consent, "action", None) == "accept" and getattr(consent, "data", None) is True


@mcp.tool()
async def save_trip_plan(title: str, content: str, ctx: Context) -> dict[str, Any]:
    """Guarda un plan propio (no una reserva), previa confirmacion del usuario."""
    owner = principal("plans:write").subject
    title, content = title.strip(), content.strip()
    if not 1 <= len(title) <= 120 or not 1 <= len(content) <= 6000:
        raise ToolError("Titulo de 1-120 caracteres y plan de 1-6000 caracteres obligatorios.")
    if not await confirmed(ctx, f"Guardar el plan '{title}':\n{content}"):
        return {"status": "cancelled"}
    principal("plans:write")
    plan_id = hashlib.sha256(f"{owner}\0{title}\0{content}".encode()).hexdigest()[:24]
    plan = {"id": plan_id, "title": title, "content": content, "created_at": int(time.time())}
    result = database().eval(
        "if redis.call('HEXISTS',KEYS[1],ARGV[1])==1 then return 0 end; "
        "if redis.call('HLEN',KEYS[1])>=tonumber(ARGV[3]) then return -1 end; "
        "redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); return 1",
        1, f"plans:{owner}", plan_id, json.dumps(plan), settings.max_plans,
    )
    if result == -1:
        raise ToolError(f"Limite de {settings.max_plans} planes alcanzado.")
    return {"status": "saved" if result == 1 else "already_saved", "plan": plan}


@mcp.tool()
async def list_trip_plans() -> dict[str, Any]:
    """Lista exclusivamente los planes del usuario autenticado."""
    owner = principal("plans:read").subject
    plans = [json.loads(raw) for raw in database().hvals(f"plans:{owner}")]
    return {"plans": sorted(plans, key=lambda item: item["created_at"], reverse=True)}


@mcp.tool()
async def delete_trip_plan(plan_id: str, ctx: Context) -> dict[str, str]:
    """Elimina un plan propio, previa confirmacion explicita."""
    owner = principal("plans:write").subject
    if len(plan_id) != 24 or any(char not in "0123456789abcdef" for char in plan_id):
        raise ToolError("Identificador de plan invalido.")
    raw = database().hget(f"plans:{owner}", plan_id)
    if raw is None:
        raise ToolError("No se encontro ese plan entre tus planes guardados.")
    plan = json.loads(raw)
    if not await confirmed(ctx, f"Eliminar el plan '{plan['title']}' ({plan_id})"):
        return {"status": "cancelled"}
    principal("plans:write")
    database().hdel(f"plans:{owner}", plan_id)
    return {"status": "deleted", "id": plan_id}


async def health(request):
    database().ping()
    key_client().get_signing_keys()
    return JSONResponse({"status": "ready"})


protected_app = mcp.http_app(
    path="/mcp", stateless_http=False,
    middleware=[Middleware(bearer_middleware), Middleware(SessionBindingMiddleware)],
    session_idle_timeout=150,
)
app = Starlette(
    routes=[Route("/health/ready", health), Mount("/", protected_app)],
    lifespan=protected_app.lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)