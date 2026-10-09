import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self


def load_env_file(path: Path) -> None:
    """Carga CLAVE=VALOR desde un archivo .env sin sobrescribir variables ya definidas."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class LLMConfig:
    api_url: str
    model: str
    api_key: str

    @classmethod
    def from_env(cls) -> Self:
        values = {
            name: os.environ.get(name, "")
            for name in ("LLM_API_URL", "LLM_MODEL", "LLM_API_KEY")
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")
        return cls(
            api_url=values["LLM_API_URL"],
            model=values["LLM_MODEL"],
            api_key=values["LLM_API_KEY"],
        )
