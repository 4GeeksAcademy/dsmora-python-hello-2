from ddgs import DDGS

from .tools import API_ERROR_TEXT, Tool

MAX_RESULTS = 10


def search_web(query: str, max_results: int = 5) -> str:
    """Busca en la web y devuelve títulos, enlaces y resúmenes."""
    query = query.strip()
    if not query:
        return "Error: la búsqueda no puede estar vacía."

    max_results = max(1, min(int(max_results), MAX_RESULTS))
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception:  # ddgs lanza sus propias excepciones según el motor
        return API_ERROR_TEXT

    if not results:
        return f"No se encontraron resultados para '{query}'."
    return "\n".join(
        f"{index}. {item.get('title', '')} ({item.get('href', '')})\n   {item.get('body', '')}"
        for index, item in enumerate(results, 1)
    )


WEB_SEARCH_TOOL = Tool(
    name="search_web",
    description="Busca información actual en internet. Úsala para noticias, datos recientes o temas generales.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto a buscar, por ejemplo 'eventos en Madrid este fin de semana'"},
            "max_results": {"type": "integer", "description": "Número de resultados (1 a 10)", "default": 5},
        },
        "required": ["query"],
    },
    function=search_web,
)
