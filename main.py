import sys
import os
from pathlib import Path

import redis

from dsmora_python_hello_2.config import LLMConfig, MemoryConfig, load_env_file
from dsmora_python_hello_2.llm import OpenAICompatibleModel
from dsmora_python_hello_2.memory import UserMemory
from dsmora_python_hello_2.factory import build_orchestrator
from dsmora_python_hello_2.mcp_weather.client import call_tool, terminal_consent


def main() -> None:
    load_env_file(Path(__file__).with_name(".env"))
    if "--web" in sys.argv:
        from dsmora_python_hello_2.web_cli import main as web_main

        web_main(login="--login" in sys.argv)
        return
    try:
        config = LLMConfig.from_env()
    except RuntimeError as error:
        print(error)
        sys.exit(1)

    # El agente principal y los dos subagentes comparten el mismo modelo de las variables de entorno.
    model = OpenAICompatibleModel(config.api_url, config.model, config.api_key)
    memory_config = MemoryConfig.from_env()
    try:
        memory = UserMemory.from_url(memory_config.redis_url, memory_config.user_id)
    except redis.RedisError:
        print("Aviso: no se pudo conectar a Redis; el agente funcionará sin memoria persistente.")
        memory = None
    token = os.getenv("MCP_ACCESS_TOKEN")
    invoke = (
        (lambda name, arguments: call_tool(name, arguments, token, terminal_consent))
        if token else None
    )
    if not token:
        print("Modo planificacion. Para herramientas autenticadas usa --web --login.")
    agent = build_orchestrator(model=model, invoke=invoke, memory=memory, on_event=print)
    print("Sistema multiagente de planes y viajes. Escribe 'salir' para terminar.")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in {"salir", "exit"}:
            break
        if not user_input:
            continue

        try:
            print(agent.run(user_input))
        except RuntimeError as error:
            print(f"Error: {error}")


if __name__ == "__main__":
    main()