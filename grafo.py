from dsmora_python_hello_2.orchestrator import Orchestrator
from dsmora_python_hello_2.subagents import build_planner_agent, build_weather_agent
from dsmora_python_hello_2.tools import WEATHER_TOOL

subagents = [build_weather_agent(None, WEATHER_TOOL), build_planner_agent(None)]
graph = Orchestrator(model=None, subagents=subagents).graph

# Mermaid como texto (para pegar en cualquier renderizador)
print(graph.get_graph().draw_mermaid())

# ASCII en terminal
print(graph.get_graph().draw_ascii())

# PNG (requiere conexión a internet)
graph.get_graph().draw_mermaid_png(output_file_path="grafo.png")
