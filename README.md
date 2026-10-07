# Demo RAG con Python, `uv`, tags y embeddings

Esta demo implementa los pasos del ejemplo de referencia: **embed → indexar → recuperar → generar**. Los tags se guardan como metadata en Qdrant y pueden limitar la búsqueda semántica. No se usa un framework de orquestación.

## Qué modelo usa

- **Embeddings**: llamada HTTP al modelo `litellm/madrid-spain/openrouter/perplexity/pplx-embed-v1-0.6b` en `https://llm.4geeks.ai/v1`.
- **Generación**: por defecto Ollama local con `llama3.2:3b`, un modelo preentrenado/instruct. La llamada usa una API compatible con OpenAI.
- **Vector DB**: Qdrant en memoria para que la demo arranque sin Docker ni servicio externo. Los datos se reconstruyen cada vez que se ejecuta.

> Esto utiliza modelos preentrenados, no entrena un modelo nuevo. El modelo de embeddings transforma texto en vectores; el LLM genera la respuesta.

## Requisitos

Instala [`uv`](https://docs.astral.sh/uv/getting-started/installation/) y Python 3.10 o superior. La ejecución requiere acceso a `https://llm.4geeks.ai` y una API key válida.

Crea un archivo `.env` en la raíz del proyecto:

```dotenv
4GEEKS_API_KEY=tu-api-key
```

No subas `.env` al repositorio ni compartas su contenido.

```bash
uv sync
```

### Ejecutar la demo completa

Instala [Ollama](https://ollama.com/) y descarga el modelo:

```bash
ollama pull llama3.2:3b
```

Asegúrate de que Ollama esté corriendo (normalmente inicia el servicio al instalarse) y ejecuta:

```bash
uv run python main.py
```

Puedes pasar otra pregunta:

```bash
uv run python main.py "¿Qué cursos ofrece 4Geeks?"
```

### Comparar respuesta directa vs RAG (útil para la clase)

Ambos comandos usan el mismo `LLM_API_URL` y `LLM_MODEL`. El modo directo envía únicamente la pregunta al LLM; no llama a embeddings ni consulta Qdrant. El modo RAG recupera documentos primero y pasa esos textos como contexto al mismo modelo.

```bash
# Baseline: solo LLM, sin embeddings ni búsqueda documental
uv run python main.py "¿En qué ciudades tiene campus 4Geeks Academy?" --no-rag

# RAG: embeddings + Qdrant + el mismo LLM
uv run python main.py "¿En qué ciudades tiene campus 4Geeks Academy?"
```

La respuesta directa refleja lo que el modelo ya conoce y puede no saber los datos de esta demo; la respuesta RAG debería fundamentarse en el contexto recuperado. Ambos modos requieren que el endpoint generativo configurado esté disponible; solo RAG requiere además `4GEEKS_API_KEY` y acceso al servicio de embeddings. No combines `--no-rag` con `--tag` o `--retrieve-only`.

Filtra la recuperación por un tag disponible (`academy`, `campuses`, `courses`, `ai`, `data-science`, `tools`, `learnpack`, `rigobot`) y cambia el número máximo de resultados:

```bash
uv run python main.py "¿Qué herramientas ayudan a los estudiantes?" --tag tools --limit 2
```

Para probar embeddings, tags y búsqueda vectorial, sin iniciar el LLM generativo:

```bash
uv run python main.py "¿Dónde están los campus?" --retrieve-only
```

### Configurar otro endpoint compatible

El endpoint de embeddings puede sobrescribirse con `EMBEDDING_API_URL` (por defecto `https://llm.4geeks.ai/v1`) y `EMBEDDING_MODEL`. Para generación se aceptan endpoints con formato OpenAI Chat Completions, por ejemplo un gateway o un servidor local compatible:

```bash
export LLM_API_URL="https://api.openai.com/v1"
export LLM_API_KEY="tu-api-key"
export LLM_MODEL="gpt-4o-mini"
uv run python main.py
```

La clave de embeddings `4GEEKS_API_KEY` solo se envía al endpoint de embeddings. Para el LLM generativo configura aparte `LLM_API_KEY`; Ollama local no requiere clave. También puedes cambiar `QDRANT_COLLECTION` mediante variables de entorno.

## Cómo está armado

1. `embed()` llama a la API de embeddings y `build_demo()` indexa los vectores junto con `text` y `tags` en Qdrant.
2. `retrieve()` embebe la pregunta y busca los vectores más cercanos. Con `--tag`, añade un filtro de payload para recuperar únicamente documentos etiquetados.
3. `generate_answer()` envía pregunta y contexto al modelo generativo. Con `--no-rag`, envía solo la pregunta para comparar el baseline sin recuperación.

La base de conocimiento de ejemplo está en `DOCUMENTS` dentro de `main.py`; puedes editar o ampliar su texto y sus tags.

## Consideraciones para evolucionar la demo

- Qdrant está en memoria: para persistir índices, utiliza Qdrant local/Cloud y configura el cliente con URL y credenciales.
- En una aplicación real añade chunking, ingesta de documentos, umbral de score calibrado con datos de evaluación, manejo de errores y tests.
- Un filtro de tags es un filtro exacto de metadata, no un clasificador automático de intención. El usuario o la aplicación decide qué tag usar.
- Cada texto (documento y pregunta) genera una llamada al endpoint de embeddings; protege la clave y considera los límites/costes del proveedor.
