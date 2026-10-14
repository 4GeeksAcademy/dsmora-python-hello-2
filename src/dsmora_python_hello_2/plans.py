from datetime import date

from .tools import API_ERROR_TEXT, FORECAST_URL, WEATHER_CODES, Tool, find_place, get_json

# Códigos WMO de lluvia, llovizna, nieve y tormenta.
BAD_WEATHER_CODES = {51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99}
RAIN_PROBABILITY_LIMIT = 50
HOT_TEMPERATURE = 30
COLD_TEMPERATURE = 5

INDOOR_PLANS = ["Museos o galerías", "Cine o teatro", "Mercados cubiertos y cafés", "Spa o termas"]
OUTDOOR_PLANS = ["Paseo por el centro histórico", "Parques, jardines o miradores", "Picnic o terrazas"]


def recommend_for_weather(code: int, tmax: float, tmin: float, rain_probability: float) -> list[str]:
    """Devuelve planes adecuados para unas condiciones meteorológicas diarias."""
    if code in BAD_WEATHER_CODES or rain_probability >= RAIN_PROBABILITY_LIMIT:
        plans = list(INDOOR_PLANS)
    else:
        plans = list(OUTDOOR_PLANS)
    if tmax >= HOT_TEMPERATURE:
        plans.append("Piscina o playa a primera hora; evita el sol de 12:00 a 17:00")
    if tmin <= COLD_TEMPERATURE:
        plans.append("Rutas cortas con abrigo y paradas en cafés con calefacción")
    return plans


def recommend_plans(city: str, day: str | None = None) -> str:
    """Recomienda planes según la previsión del tiempo de una ciudad para un día."""
    city = city.strip()
    if not city:
        return "Error: la ciudad no puede estar vacía."

    try:
        target = date.fromisoformat(day) if day else date.today()
    except ValueError:
        return "Error: la fecha debe tener formato AAAA-MM-DD."

    try:
        place = find_place(city)
        if place is None:
            return f"Error: no se encontró la ciudad '{city}'."

        forecast = get_json(
            FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "start_date": target.isoformat(),
                "end_date": target.isoformat(),
                "timezone": "auto",
            },
        )
        daily = forecast.get("daily")
        if not daily:
            return API_ERROR_TEXT
        units = forecast["daily_units"]
        code = daily["weather_code"][0]
        tmax = daily["temperature_2m_max"][0]
        tmin = daily["temperature_2m_min"][0]
        rain = daily["precipitation_probability_max"][0] or 0
    except Exception:
        return API_ERROR_TEXT

    condition = WEATHER_CODES.get(code, "estado desconocido")
    summary = (
        f"Previsión para {place['name']} el {target.isoformat()}: {condition}, "
        f"máxima {tmax} {units['temperature_2m_max']}, mínima {tmin} {units['temperature_2m_min']}, "
        f"probabilidad de lluvia {rain} {units['precipitation_probability_max']}."
    )
    plans = recommend_for_weather(code, tmax, tmin, rain)
    return "\n".join([summary, "Planes recomendados:", *(f"- {plan}" for plan in plans)])


PLANS_TOOL = Tool(
    name="recommend_plans",
    description="Recomienda planes para una ciudad según la previsión del tiempo (lluvia, calor o frío) de un día.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Ciudad, por ejemplo Valencia"},
            "day": {"type": "string", "description": "Fecha en formato AAAA-MM-DD. Si se omite, es hoy."},
        },
        "required": ["city"],
    },
    function=recommend_plans,
)
