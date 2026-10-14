import sys
from pathlib import Path

from dsmora_python_hello_2.agent import Agent
from dsmora_python_hello_2.config import LLMConfig, load_env_file
from dsmora_python_hello_2.flights import FLIGHT_TOOL
from dsmora_python_hello_2.llm import OpenAICompatibleModel
from dsmora_python_hello_2.plans import PLANS_TOOL
from dsmora_python_hello_2.restaurants import RESTAURANT_TOOL
from dsmora_python_hello_2.tools import WEATHER_TOOL
from dsmora_python_hello_2.web_search import WEB_SEARCH_TOOL


def main() -> None:
    load_env_file(Path(__file__).with_name(".env"))
    try:
        config = LLMConfig.from_env()
    except RuntimeError as error:
        print(error)
        sys.exit(1)

    model = OpenAICompatibleModel(config.api_url, config.model, config.api_key)
    tools = [WEATHER_TOOL, PLANS_TOOL, WEB_SEARCH_TOOL, FLIGHT_TOOL, RESTAURANT_TOOL]
    agent = Agent(model=model, tools=tools)
    print("Agente de planes y viajes. Escribe 'salir' para terminar.")

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