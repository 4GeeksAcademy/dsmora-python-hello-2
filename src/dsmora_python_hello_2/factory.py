import json
from typing import Any, Callable

from .memory import UserMemory
from .model import Model
from .orchestrator import Orchestrator
from .subagents import COMMON_RULES, SubAgent, build_planner_agent, build_weather_agent
from .tools import Tool

PLAN_SCHEMAS = {
    "save_trip_plan": (
        "Guarda un plan de viaje propio con confirmacion del usuario; nunca reserva.",
        {"title": {"type": "string"}, "content": {"type": "string"}}, ["title", "content"],
    ),
    "list_trip_plans": ("Lista tus planes de viaje guardados.", {}, []),
    "delete_trip_plan": (
        "Elimina un plan propio por ID con confirmacion del usuario.",
        {"plan_id": {"type": "string"}}, ["plan_id"],
    ),
}


def build_orchestrator(
    model: Model,
    invoke: Callable[[str, dict[str, Any]], Any] | None = None,
    memory: UserMemory | None = None,
    on_event: Callable[[str], None] | None = None,
) -> Orchestrator:
    subagents = [build_planner_agent(model)]
    if invoke is not None:
        def tool(name: str, description: str, properties: dict, required: list[str]) -> Tool:
            def run(**arguments) -> str:
                result = invoke(name, arguments)
                return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

            return Tool(
                name=name, description=description,
                parameters={"type": "object", "properties": properties, "required": required},
                function=run,
            )

        weather = tool("get_weather", "Consulta el tiempo con consentimiento.", {"city": {"type": "string"}}, ["city"])
        subagents.append(build_weather_agent(model, weather))
        subagents.append(SubAgent(
            name="saved_plans",
            description="Guarda, lista o elimina planes de viaje propios. No hace reservas.",
            model=model,
            system_prompt=(
                "Gestionas planes guardados. Usa las herramientas para guardar, listar o eliminar; "
                "nunca afirmes exito sin resultado. No inventes IDs; consulta list_trip_plans si hace falta. "
                "Una cancelacion no es exito. Las confirmaciones las gestiona la herramienta.\n" + COMMON_RULES
            ),
            tools=[tool(name, *schema) for name, schema in PLAN_SCHEMAS.items()],
        ))
    return Orchestrator(
        model=model, subagents=subagents, memory=memory, on_event=on_event,
        capability_notice=(
            "Puedes planificar y usar clima y planes guardados; las herramientas requieren confirmacion."
            if invoke is not None else
            "Esta es una sesion de invitado: SOLO planificacion. Si pide clima o guardar/listar/eliminar "
            "planes, indica que debe iniciar sesion. No simules esas operaciones. Resuelve la parte de "
            "planificacion si tambien la pide."
        ),
    )
