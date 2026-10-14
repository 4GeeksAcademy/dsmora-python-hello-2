import os
import re
from datetime import date
from typing import Any

from .tools import API_ERROR_TEXT, Tool, get_json, post_form_json

AMADEUS_BASE_URL = "https://test.api.amadeus.com"
IATA_PATTERN = re.compile(r"[A-Z]{3}")
MAX_RESULTS = 10


def _format_itinerary(label: str, itinerary: dict[str, Any]) -> str:
    segments = itinerary["segments"]
    first, last = segments[0], segments[-1]
    carriers = ", ".join(sorted({segment["carrierCode"] for segment in segments}))
    return (
        f"{label}: {first['departure']['iataCode']} {first['departure']['at']} -> "
        f"{last['arrival']['iataCode']} {last['arrival']['at']} "
        f"(escalas: {len(segments) - 1}, aerolíneas: {carriers})"
    )


def _format_offer(index: int, offer: dict[str, Any]) -> str:
    price = offer["price"]
    legs = [
        _format_itinerary("ida" if position == 0 else "vuelta", itinerary)
        for position, itinerary in enumerate(offer["itineraries"])
    ]
    return f"{index}. {price['total']} {price['currency']} | " + " | ".join(legs)


def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adults: int = 1,
    max_results: int = 5,
) -> str:
    """Busca vuelos con la API de Amadeus."""
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    if not (IATA_PATTERN.fullmatch(origin) and IATA_PATTERN.fullmatch(destination)):
        return "Error: origen y destino deben ser códigos IATA de 3 letras, por ejemplo MAD o BCN."

    try:
        departure = date.fromisoformat(departure_date)
        returning = date.fromisoformat(return_date) if return_date else None
    except ValueError:
        return "Error: las fechas deben tener formato AAAA-MM-DD."
    if departure < date.today():
        return "Error: la fecha de salida no puede ser anterior a hoy."
    if returning is not None and returning < departure:
        return "Error: la fecha de vuelta no puede ser anterior a la de salida."

    client_id = os.environ.get("AMADEUS_CLIENT_ID", "")
    client_secret = os.environ.get("AMADEUS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return API_ERROR_TEXT

    params: dict[str, Any] = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure.isoformat(),
        "adults": max(1, min(int(adults), 9)),
        "max": max(1, min(int(max_results), MAX_RESULTS)),
        "currencyCode": "EUR",
    }
    if returning is not None:
        params["returnDate"] = returning.isoformat()

    try:
        token = post_form_json(
            f"{AMADEUS_BASE_URL}/v1/security/oauth2/token",
            {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        )["access_token"]
        offers = get_json(
            f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers",
            params,
            headers={"Authorization": f"Bearer {token}"},
        ).get("data", [])
    except Exception:
        return API_ERROR_TEXT

    if not offers:
        return f"No se encontraron vuelos de {origin} a {destination} para esas fechas."
    return "\n".join(_format_offer(index, offer) for index, offer in enumerate(offers, 1))


FLIGHT_TOOL = Tool(
    name="search_flights",
    description=(
        "Busca vuelos entre dos aeropuertos para una fecha. Necesita códigos IATA de 3 letras "
        "(MAD para Madrid, BCN para Barcelona); si el usuario indica una ciudad, usa su código IATA principal."
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Código IATA de origen, por ejemplo MAD"},
            "destination": {"type": "string", "description": "Código IATA de destino, por ejemplo BCN"},
            "departure_date": {"type": "string", "description": "Fecha de salida en formato AAAA-MM-DD"},
            "return_date": {"type": "string", "description": "Fecha de vuelta opcional en formato AAAA-MM-DD"},
            "adults": {"type": "integer", "description": "Número de adultos (1 a 9)", "default": 1},
            "max_results": {"type": "integer", "description": "Número de ofertas (1 a 10)", "default": 5},
        },
        "required": ["origin", "destination", "departure_date"],
    },
    function=search_flights,
)
