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