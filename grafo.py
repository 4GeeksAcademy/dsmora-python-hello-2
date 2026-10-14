from dsmora_python_hello_2.agent import Agent
from dsmora_python_hello_2.tools import WEATHER_TOOL

graph = Agent(model=None, tools=[WEATHER_TOOL]).graph

# Mermaid como texto (para pegar en cualquier renderizador)
print(graph.get_graph().draw_mermaid())

# ASCII en terminal
print(graph.get_graph().draw_ascii())

# PNG (requiere conexión a internet)
graph.get_graph().draw_mermaid_png(output_file_path="grafo.png")
