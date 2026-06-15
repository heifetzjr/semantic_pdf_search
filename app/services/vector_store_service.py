from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
import uuid

COLLECTION_NAME = "pdf_chunks"
VECTOR_SIZE     = 768        # paraphrase-multilingual-mpnet-base-v2 → 768
                              # all-MiniLM-L6-v2                      → 384
QDRANT_PATH     = "./qdrant_storage"

# ── Instância única e global ─────────────────────────────────────────
# O modo local do Qdrant NÃO suporta múltiplas instâncias simultâneas.
# Por isso criamos UMA SÓ vez e reutilizamos em todo o projeto.
_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """
    Retorna sempre a mesma instância do cliente Qdrant (singleton).
    """
    global _client
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
    return _client


def init_vector_store() -> QdrantClient:
    """
    Inicializa o cliente e cria a coleção se ainda não existir.
    Deve ser chamado uma vez na inicialização do app.
    """
    client   = get_client()
    existing = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )
        print(f"[Qdrant] Coleção '{COLLECTION_NAME}' criada.")
    else:
        print(f"[Qdrant] Coleção '{COLLECTION_NAME}' já existe.")

    return client


def clear_vector_store() -> QdrantClient:
    """
    Apaga e recria a coleção usando a instância já existente.
    NÃO cria uma nova instância — reutiliza o singleton.
    """
    client   = get_client()
    existing = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME in existing:
        client.delete_collection(collection_name=COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )
    print(f"[Qdrant] Coleção '{COLLECTION_NAME}' limpa e recriada.")
    return client


def add_documents(client: QdrantClient, embeddings: list, docs_metadata: list):
    """Adiciona documentos em lotes de 500."""
    BATCH_SIZE = 500
    total      = len(docs_metadata)

    for start in range(0, total, BATCH_SIZE):
        end        = min(start + BATCH_SIZE, total)
        batch_meta = docs_metadata[start:end]
        batch_emb  = embeddings[start:end]

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=batch_emb[i],
                payload=batch_meta[i],
            )
            for i in range(len(batch_meta))
        ]

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
        print(f"[Qdrant] Indexados {end}/{total} chunks.")


def similarity_search(
    client: QdrantClient,
    query_embedding: list,
    top_k: int = 10,
) -> list:
    """
    Busca os trechos mais relevantes usando query_points()
    (API do qdrant-client >= 1.7 — .search() foi removido).
    """
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        limit=top_k,
        with_payload=True,
    )

    points = response.points if hasattr(response, "points") else response

    return [
        {
            "id":       str(p.id),
            "score":    p.score,
            "document": p.payload.get("text", ""),
            "metadata": p.payload,
        }
        for p in points
    ]


def delete_documents_by_file(client: QdrantClient, file_id: str):
    """Remove todos os chunks de um PDF pelo file_id."""
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="file_id",
                    match=MatchValue(value=file_id),
                )
            ]
        ),
    )
    print(f"[Qdrant] Chunks removidos para file_id={file_id}")
