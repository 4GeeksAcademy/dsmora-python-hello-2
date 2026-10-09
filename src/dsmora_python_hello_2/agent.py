from .model import Message, Model, ToolCall
from .tools import Tool

SYSTEM_PROMPT = (
    "Eres un asistente que responde en español. "
    "Usa las herramientas disponibles cuando necesites datos externos."
)


class Context:
    """Historial de mensajes que se envía al modelo en cada paso."""

    def __init__(self, system_prompt: str) -> None:
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    def add(self, message: Message) -> None:
        self.messages.append(message)


class Agent:
    def __init__(
        self,
        model: Model,
        tools: list[Tool],
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 5,
    ) -> None:
        self.model = model
        self.tools = {tool.name: tool for tool in tools}
        self.context = Context(system_prompt)
        self.max_steps = max_steps

    def run(self, user_input: str) -> str:
        """Bucle de orquestación: consulta al modelo hasta obtener una respuesta final."""
        self.context.add(Message(role="user", content=user_input))
        schemas = [tool.schema() for tool in self.tools.values()]

        for _ in range(self.max_steps):
            response = self.model.generate(self.context.messages, schemas)

            if response.tool_call is None:
                text = response.text or ""
                self.context.add(Message(role="assistant", content=text))
                return text

            call = response.tool_call
            self.context.add(Message(role="assistant", content="", tool_call=call))
            result = self._execute(call)
            self.context.add(Message(role="tool", content=result, tool_call_id=call.id))

        return "No se obtuvo una respuesta final dentro del límite de pasos."

    def _execute(self, call: ToolCall) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Error: la herramienta '{call.name}' no existe."
        try:
            return tool.run(call.arguments)
        except TypeError as error:
            return f"Error en los argumentos de '{call.name}': {error}"
