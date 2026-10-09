<<<<<<< Updated upstream
"""Tag-aware RAG demo: 4Geeks embeddings, Qdrant, and an OpenAI-compatible LLM."""

from __future__ import annotations

import argparse
import os
from typing import Any

import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

load_dotenv()

COLLECTION = os.getenv("QDRANT_COLLECTION", "geeks_knowledge")
EMBEDDING_API_URL = os.getenv(
	"EMBEDDING_API_URL", "https://llm.4geeks.ai/v1"
).rstrip("/")
EMBEDDING_MODEL = os.getenv(
	"EMBEDDING_MODEL", "madrid-spain/openrouter/perplexity/pplx-embed-v1-0.6b"
)
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
API_KEY = os.getenv("4GEEKS_API_KEY")
LLM_API_KEY = os.getenv("LLM_API_KEY")  # Separate from the embeddings API key.

# Small sample knowledge base. Tags are stored as Qdrant payload metadata, so
# retrieval can combine semantic similarity with a tag filter.
DOCUMENTS = [
	{
		"id": 1,
		"text": "4Geeks Academy is a coding bootcamp with campuses in Miami and Spain.",
		"tags": ["academy", "campuses"],
	},
	{
		"id": 2,
		"text": "4Geeks courses cover Full Stack, Data Science, and AI Engineering.",
		"tags": ["courses", "ai", "data-science"],
	},
	{
		"id": 3,
		"text": "LearnPack is 4Geeks' interactive platform for coding exercises.",
		"tags": ["tools", "learnpack"],
	},
	{
		"id": 4,
		"text": "Rigobot is 4Geeks' AI tutor that guides students through their learning.",
		"tags": ["tools", "ai", "rigobot"],
	},
]


def embed(text: str) -> list[float]:
	"""Get an embedding from the configured 4Geeks-compatible API."""
	if not API_KEY:
		raise ValueError("Define 4GEEKS_API_KEY en tu archivo .env")
	try:
		response = requests.post(
			f"{EMBEDDING_API_URL}/embeddings",
			headers={"Authorization": f"Bearer {API_KEY}"},
			json={"model": EMBEDDING_MODEL, "input": text},
			timeout=120,
		)
		response.raise_for_status()
	except requests.RequestException as error:
		raise RuntimeError(
			f"Falló la llamada de embeddings a {EMBEDDING_API_URL}/embeddings "
			f"(HTTP {error.response.status_code if error.response is not None else 'sin respuesta'}). "
			"Verifica 4GEEKS_API_KEY, el endpoint y el nombre del modelo; no imprimas ni compartas la clave."
		) from error
	return response.json()["data"][0]["embedding"]


def build_demo() -> QdrantClient:
	"""Create an in-memory Qdrant index from the sample documents."""
	vectors = [embed(document["text"]) for document in DOCUMENTS]

	client = QdrantClient(location=":memory:")
	client.create_collection(
		collection_name=COLLECTION,
		vectors_config=models.VectorParams(
			size=len(vectors[0]), distance=models.Distance.COSINE
		),
	)
	client.upsert(
		collection_name=COLLECTION,
		points=[
			models.PointStruct(
				id=document["id"],
				vector=vector,
				payload={"text": document["text"], "tags": document["tags"]},
			)
			for document, vector in zip(DOCUMENTS, vectors, strict=True)
		],
	)
	return client


def retrieve(
	client: QdrantClient,
	question: str,
	limit: int = 3,
	tag: str | None = None,
) -> list[dict[str, Any]]:
	"""Find semantically similar documents, optionally restricted to one tag."""
	query_vector = embed(question)
	query_filter = (
		models.Filter(
			must=[models.FieldCondition(key="tags", match=models.MatchValue(value=tag))]
		)
		if tag
		else None
	)
	result = client.query_points(
		collection_name=COLLECTION,
		query=query_vector,
		query_filter=query_filter,
		limit=limit,
		with_payload=True,
	)
	return [
		{
			"text": point.payload["text"],
			"tags": point.payload["tags"],
			"score": point.score,
		}
		for point in result.points
	]


def generate_answer(
	question: str,
	matches: list[dict[str, Any]] | None = None,
	use_rag: bool = True,
) -> str:
	"""Call the chat model, with retrieved context or as a direct baseline."""
	headers = {"Content-Type": "application/json"}
	if LLM_API_KEY:
		headers["Authorization"] = f"Bearer {LLM_API_KEY}"
	if use_rag:
		context = "\n".join(
			f"- [{', '.join(item['tags'])}] {item['text']}"
			for item in (matches or [])
		) or "No relevant documents were found."
		system_prompt = (
			"Answer in Spanish using only the supplied context. "
			"If it does not contain the answer, say you don't know."
		)
		user_prompt = f"Context:\n{context}\n\nQuestion: {question}"
	else:
		system_prompt = "You are a helpful assistant. Answer the user's question in Spanish."
		user_prompt = question

	try:
		response = requests.post(
			f"{LLM_API_URL}/chat/completions",
			headers=headers,
			json={
				"model": LLM_MODEL,
				"temperature": 0,
				"messages": [
					{"role": "system", "content": system_prompt},
					{"role": "user", "content": user_prompt},
				],
			},
			timeout=120,
		)
		response.raise_for_status()
	except requests.RequestException as error:
		raise RuntimeError(
			"No se pudo contactar el modelo generativo. Inicia Ollama y descarga "
			f"'{LLM_MODEL}' (ver README), o configura LLM_API_URL/LLM_MODEL. "
			"Para probar solo la recuperación, usa --retrieve-only."
		) from error

	return response.json()["choices"][0]["message"]["content"]


def main() -> None:
	parser = argparse.ArgumentParser(description="Demo RAG con filtros por tag")
	parser.add_argument(
		"question",
		nargs="?",
		default="¿En qué ciudades tiene campus 4Geeks Academy?",
		help="Pregunta para la base de conocimiento",
	)
	parser.add_argument("--tag", help="Limita la búsqueda a este tag")
	parser.add_argument("--limit", type=int, default=3, help="Máximo de resultados")
	parser.add_argument(
		"--retrieve-only",
		action="store_true",
		help="Muestra resultados sin llamar al modelo generativo",
	)
	parser.add_argument(
		"--no-rag",
		action="store_true",
		help="Pregunta directamente al LLM, sin embeddings, Qdrant ni contexto recuperado",
	)
	args = parser.parse_args()
	if args.limit < 1:
		parser.error("--limit debe ser mayor que cero")
	if args.no_rag and args.retrieve_only:
		parser.error("--no-rag y --retrieve-only no se pueden usar juntos")
	if args.no_rag and args.tag:
		parser.error("--tag requiere RAG; no se puede usar con --no-rag")

	print(f"Pregunta: {args.question}")
	if args.no_rag:
		print("Modo: LLM directo (sin RAG ni embeddings)")
		print("\nRespuesta:")
		print(generate_answer(args.question, use_rag=False))
		return

	client = build_demo()
	matches = retrieve(client, args.question, args.limit, args.tag)

	print("Modo: RAG (embeddings + Qdrant + LLM)")
	if args.tag:
		print(f"Filtro tag: {args.tag}")
	print("\nContexto recuperado:")
	if not matches:
		print("  (sin resultados)")
	for item in matches:
		print(f"  [{item['score']:.3f}] [{', '.join(item['tags'])}] {item['text']}")

	if not args.retrieve_only:
		print("\nRespuesta:")
		print(generate_answer(args.question, matches))


if __name__ == "__main__":
	main()
=======
"""Pipeline de ejemplo: ingesta, generación con RAG o generación directa."""

import argparse
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from qdrant_client import QdrantClient, models

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # Las variables también se pueden establecer directamente en el entorno.
    pass


DOCUMENTS = [
    "4Geeks Academy is a coding bootcamp with campuses in Miami and Spain.",
    "4Geeks courses cover Full Stack, Data Science, and AI Engineering.",
    "LearnPack is 4Geeks' interactive exercises platform.",
    "Rigobot is 4Geeks' AI tutor that guides students.",
]
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "learning_resources")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "./qdrant_data")


def _post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    service_name: str,
) -> dict[str, Any]:
    """Hace POST JSON y normaliza los errores de los servicios compatibles con OpenAI."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{service_name} respondió HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"No se pudo conectar con {service_name}: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{service_name} devolvió una respuesta JSON inválida.") from error


def _endpoint(base_url: str, path: str) -> str:
    """Acepta URL base (/v1) o endpoint completo (/v1/embeddings, /v1/chat/completions)."""
    base_url = base_url.rstrip("/")
    if base_url.endswith(path):
        return base_url
    return f"{base_url}/{path.lstrip('/')}"


def create_embedding(text: str) -> list[float]:
    """Crea un vector mediante un endpoint de embeddings compatible con OpenAI."""
    api_url = os.getenv("EMBEDDING_API_URL")
    model = os.getenv("EMBEDDING_MODEL")
    api_key = os.getenv("EMBEDDING_API_KEY")
    missing = [
        name
        for name, value in (
            ("EMBEDDING_API_URL", api_url),
            ("EMBEDDING_MODEL", model),
            ("EMBEDDING_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    result = _post_json(
        _endpoint(api_url, "/embeddings"),
        {"model": model, "input": text},
        api_key,
        "Servicio de embeddings",
    )
    try:
        vector = [float(value) for value in result["data"][0]["embedding"]]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError(
            "Respuesta de embeddings inesperada; se esperaba data[0].embedding."
        ) from error
    if not vector:
        raise RuntimeError("El servicio de embeddings devolvió un vector vacío.")
    return vector


def generate_answer(prompt: str, use_rag: bool) -> str:
    """Envía la consulta (y opcionalmente contexto recuperado) al LLM."""
    api_url = os.getenv("LLM_API_URL")
    model = os.getenv("LLM_MODEL")
    api_key = os.getenv("LLM_API_KEY")
    missing = [
        name
        for name, value in (
            ("LLM_API_URL", api_url),
            ("LLM_MODEL", model),
            ("LLM_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    system_message = (
        "Responde en español, con claridad y precisión. "
        "Si se proporciona contexto, basa la respuesta en él y no inventes datos. "
        "Si el contexto no contiene la respuesta, indícalo."
        if use_rag
        else "Responde en español, con claridad y precisión. Si no sabes algo, indícalo."
    )
    result = _post_json(
        _endpoint(api_url, "/chat/completions"),
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        api_key,
        "Servicio LLM",
    )
    try:
        return result["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError(
            "Respuesta del LLM inesperada; se esperaba choices[0].message.content."
        ) from error


def get_qdrant_client() -> QdrantClient:
    """Crea un cliente remoto si QDRANT_URL está definida, o local persistente si no."""
    api_key = os.getenv("QDRANT_API_KEY")
    if QDRANT_URL:
        client = QdrantClient(url=QDRANT_URL, api_key=api_key or None)
        try:
            client.get_collections()
        except Exception as error:
            raise RuntimeError(
                f"No se pudo conectar con Qdrant en {QDRANT_URL}. "
                "Verifica que el servidor esté activo y revisa URL/clave."
            ) from error
        return client

    print(f"Usando Qdrant local: {QDRANT_LOCAL_PATH}")
    return QdrantClient(path=QDRANT_LOCAL_PATH)


def ingest_documents(client: QdrantClient) -> None:
    """Vectoriza documentos de ejemplo y los inserta en la colección."""
    points = []
    for text in DOCUMENTS:
        vector = create_embedding(text)
        points.append(
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{COLLECTION_NAME}:{text}")),
                vector=vector,
                payload={
                    "text": text,
                    "source": "example",
                    "content_type": "learning_topic",
                },
            )
        )

    vector_size = len(points[0].vector)
    if any(len(point.vector) != vector_size for point in points):
        raise RuntimeError("El servicio devolvió embeddings con tamaños diferentes.")

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
    else:
        collection = client.get_collection(COLLECTION_NAME)
        existing_size = collection.config.params.vectors.size
        if existing_size != vector_size:
            raise RuntimeError(
                f"La colección '{COLLECTION_NAME}' tiene vectores de {existing_size} "
                f"dimensiones y el modelo genera {vector_size}. Usa otra colección o recréala."
            )

    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    print(f"Se insertaron/actualizaron {len(points)} documentos en '{COLLECTION_NAME}'.")


def search_context(client: QdrantClient, query: str, limit: int = 3) -> list[str]:
    """Busca los documentos semánticamente más cercanos a la consulta."""
    if not client.collection_exists(COLLECTION_NAME):
        raise RuntimeError(
            f"No existe la colección '{COLLECTION_NAME}'. Ejecuta primero: uv run main.py ingest"
        )

    query_vector = create_embedding(query)
    # query_points es la API actual del cliente Qdrant y devuelve puntos ordenados por similitud.
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=limit,
        with_payload=True,
    )
    return [
        str(point.payload["text"])
        for point in response.points
        if point.payload and point.payload.get("text")
    ]


def answer_query(client: QdrantClient, query: str, use_rag: bool) -> str:
    """Ejecuta generación directa o recuperación + generación (RAG)."""
    if use_rag:
        context_items = search_context(client, query)
        context = "\n".join(f"- {item}" for item in context_items)
        prompt = (
            f"Contexto recuperado de la base vectorial:\n{context or '(sin resultados)'}\n\n"
            f"Consulta del usuario:\n{query}\n\n"
            "Responde utilizando el contexto recuperado."
        )
        print("\nContexto recuperado:")
        print(context or "(sin resultados)")
    else:
        prompt = query

    return generate_answer(prompt, use_rag=use_rag)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline RAG con embeddings, Qdrant y un LLM.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ingest", help="Vectoriza e inserta los documentos de ejemplo en Qdrant")
    rag_parser = subparsers.add_parser("rag", help="Responde usando búsqueda semántica en Qdrant")
    rag_parser.add_argument("query", help="Consulta del usuario")
    direct_parser = subparsers.add_parser("direct", help="Responde sin recuperar contexto de Qdrant")
    direct_parser.add_argument("query", help="Consulta del usuario")

    args = parser.parse_args()
    client = get_qdrant_client()
    try:
        if args.command == "ingest":
            ingest_documents(client)
            return

        use_rag = args.command == "rag"
        answer = answer_query(client, args.query, use_rag=use_rag)
        print("\nRespuesta:")
        print(answer)
    finally:
        client.close()


if __name__ == "__main__":
    main()
>>>>>>> Stashed changes
