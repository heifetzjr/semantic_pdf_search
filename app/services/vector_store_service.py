from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    QueryRequest,
)
import uuid

COLLECTION_NAME = "pdf_chunks"
VECTOR_SIZE     = 768        # paraphrase-multilingual-mpnet-base-v2 → 768
                              # all-MiniLM-L6-v2                      → 384
QDRANT_PATH     = "./qdrant_storage"


def _get_client() -> QdrantClient:
    """
    Modo local (sem servidor Docker).
    Os dados ficam salvos em disco na pasta QDRANT_PATH.
    """
    return QdrantClient(path=QDRANT_PATH)


def init_vector_store() -> QdrantClient:
    """Cria a coleção se ainda não existir."""
    client   = _get_client()
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
    """Apaga e recria a coleção do zero."""
    client   = _get_client()
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
    Busca os trechos mais relevantes.
    Usa query_points() — API atual do qdrant-client >= 1.7.
    """
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        limit=top_k,
        with_payload=True,
    )

    # query_points devolve um QueryResponse com atributo .points
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
