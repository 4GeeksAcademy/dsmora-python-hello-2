import redis

from .tools import Tool

MAX_KEY_LENGTH = 50
MAX_VALUE_LENGTH = 500


class UserMemory:
    """Memoria persistente clave-valor por usuario almacenada en un hash de Redis."""

    def __init__(self, client: redis.Redis, user_id: str) -> None:
        self.client = client
        self.redis_key = f"agent:memory:{user_id}"

    @classmethod
    def from_url(cls, url: str, user_id: str) -> "UserMemory":
        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        return cls(client, user_id)

    def recall(self) -> dict[str, str]:
        return self.client.hgetall(self.redis_key)

    def remember(self, key: str, value: str) -> str:
        key, value = key.strip().lower(), value.strip()
        if not key or not value:
            return "Error: la clave y el valor no pueden estar vacíos."
        if len(key) > MAX_KEY_LENGTH or len(value) > MAX_VALUE_LENGTH:
            return "Error: la clave o el valor son demasiado largos."
        self.client.hset(self.redis_key, key, value)
        return f"Guardado: {key} = {value}"

    def forget(self, key: str) -> str:
        removed = self.client.hdel(self.redis_key, key.strip().lower())
        return f"Eliminado: {key}" if removed else f"No había nada guardado para '{key}'."

    def as_prompt(self) -> str:
        facts = self.recall()
        if not facts:
            return "No hay datos guardados del usuario."
        lines = "\n".join(f"- {key}: {value}" for key, value in sorted(facts.items()))
        return f"Datos conocidos del usuario:\n{lines}"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="save_user_memory",
                description=(
                    "Guarda de forma persistente una preferencia o dato clave del usuario "
                    "(por ejemplo nombre, idioma, ciudad). Úsala cuando el usuario comparta un dato relevante."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Nombre corto del dato, por ejemplo 'nombre' o 'idioma'"},
                        "value": {"type": "string", "description": "Valor del dato"},
                    },
                    "required": ["key", "value"],
                },
                function=self.remember,
            ),
            Tool(
                name="delete_user_memory",
                description="Elimina un dato guardado del usuario cuando pida olvidarlo.",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Nombre del dato a eliminar"},
                    },
                    "required": ["key"],
                },
                function=self.forget,
            ),
        ]
