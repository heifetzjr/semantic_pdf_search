import chromadb

COLLECTION_NAME = "pdf_chunks"


def init_vector_store(persist_directory: str = "chromadb"):
    """Abre ou cria a coleção. Preserva dados existentes."""
    client = chromadb.PersistentClient(path=persist_directory)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def clear_vector_store(persist_directory: str = "chromadb"):
    """Apaga toda a coleção e cria uma nova vazia."""
    client = chromadb.PersistentClient(path=persist_directory)
    try:
        client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass
    return client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(collection, embeddings: list, docs_metadata: list):
    """Adiciona documentos ao banco vetorial."""
    ids = [
        f"chunk_{meta['file_id']}_{meta['chunk_index']}"
        for meta in docs_metadata
    ]
    documents = [meta["text"] for meta in docs_metadata]
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=docs_metadata,
    )


def similarity_search(collection, query_embedding: list, top_k: int = 10):
    """Busca os trechos mais relevantes em todos os PDFs indexados."""
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["distances", "documents", "metadatas"],
    )

    formatted = []
    for i in range(len(results["ids"][0])):
        formatted.append({
            "id": results["ids"][0][i],
            "distance": results["distances"][0][i],
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
        })

    formatted.sort(key=lambda x: x["distance"])
    return formatted


def delete_documents_by_file(collection, file_id: str):
    """Remove todos os chunks de um PDF específico pelo file_id."""
    results = collection.get(
        where={"file_id": file_id},
        include=["documents"],
    )
    ids = results.get("ids", [])
    if ids:
        collection.delete(ids=ids)
        print(f"[ChromaDB] {len(ids)} chunks removidos para file_id={file_id}")
    else:
        print(f"[ChromaDB] Nenhum chunk encontrado para file_id={file_id}")