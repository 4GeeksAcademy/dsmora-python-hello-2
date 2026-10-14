import re
from typing import Any

from .tools import API_ERROR_TEXT, Tool, find_place, post_form_json

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SEARCH_RADIUS_METERS = 3000
MAX_RESULTS = 20
CUISINE_PATTERN = re.compile(r"[A-Za-z][A-Za-z_ -]*")

# Preferencias y dietas soportadas, con su etiqueta en OpenStreetMap.
DIET_TAGS = {
    "vegetariano": "diet:vegetarian",
    "vegano": "diet:vegan",
    "sin_gluten": "diet:gluten_free",
    "halal": "diet:halal",
    "kosher": "diet:kosher",
}


def _build_query(latitude: float, longitude: float, cuisine: str, diets: list[str], limit: int) -> str:
    filters = '["amenity"="restaurant"]'
    if cuisine:
        filters += f'["cuisine"~"{cuisine}",i]'
    for diet in diets:
        filters += f'["{DIET_TAGS[diet]}"="yes"]'
    return (
        f"[out:json][timeout:25];"
        f"nwr{filters}(around:{SEARCH_RADIUS_METERS},{latitude},{longitude});"
        f"out center {limit};"
    )


def _format_restaurant(index: int, element: dict[str, Any]) -> str:
    tags = element.get("tags", {})
    parts = [f"{index}. {tags.get('name', 'Sin nombre')}"]
    if "cuisine" in tags:
        parts.append(f"cocina: {tags['cuisine']}")
    options = [label for label, tag in DIET_TAGS.items() if tags.get(tag) in {"yes", "only"}]
    if options:
        parts.append(f"opciones: {', '.join(options)}")
    street = f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip()
    if street:
        parts.append(f"dirección: {street}")
    return " | ".join(parts)


def search_restaurants(
    city: str,
    cuisine: str | None = None,
    diets: list[str] | None = None,
    max_results: int = 10,
) -> str:
    """Busca restaurantes en una ciudad filtrando por cocina y preferencias dietéticas."""
    city = city.strip()
    if not city:
        return "Error: la ciudad no puede estar vacía."

    cuisine = (cuisine or "").strip().lower()
    if cuisine and not CUISINE_PATTERN.fullmatch(cuisine):
        return "Error: la cocina solo puede contener letras, espacios, guiones y guiones bajos."

    diets = diets or []
    unknown = [diet for diet in diets if diet not in DIET_TAGS]
    if unknown:
        return f"Error: preferencias no soportadas: {', '.join(unknown)}. Opciones: {', '.join(DIET_TAGS)}."

    limit = max(1, min(int(max_results), MAX_RESULTS))
    try:
        place = find_place(city)
        if place is None:
            return f"Error: no se encontró la ciudad '{city}'."
        query = _build_query(place["latitude"], place["longitude"], cuisine, diets, limit)
        elements = post_form_json(OVERPASS_URL, {"data": query}).get("elements", [])
    except Exception:
        return API_ERROR_TEXT

    if not elements:
        return f"No se encontraron restaurantes en {place['name']} con esos criterios."
    lines = [_format_restaurant(index, element) for index, element in enumerate(elements, 1)]
    lines.append("Nota: datos de OpenStreetMap, pueden estar incompletos. Confirma alergias e intolerancias con el local.")
    return "\n".join(lines)


RESTAURANT_TOOL = Tool(
    name="search_restaurants",
    description=(
        "Busca restaurantes en una ciudad por origen o tipo de cocina y preferencias dietéticas "
        "(vegetariano, vegano, sin gluten, halal, kosher)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Ciudad donde buscar, por ejemplo Madrid"},
            "cuisine": {
                "type": "string",
                "description": "Cocina u origen en inglés según OpenStreetMap: italian, mexican, japanese, indian, thai, spanish",
            },
            "diets": {
                "type": "array",
                "items": {"type": "string", "enum": list(DIET_TAGS)},
                "description": "Preferencias o intolerancias a cumplir. sin_gluten sirve para celiaquía.",
            },
            "max_results": {"type": "integer", "description": "Número máximo de restaurantes (1 a 20)", "default": 10},
        },
        "required": ["city"],
    },
    function=search_restaurants,
)
