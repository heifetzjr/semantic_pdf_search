import os
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

model = SentenceTransformer("all-MiniLM-L6-v2")


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Gera embeddings para uma lista de textos."""
    embeddings = model.encode(texts, convert_to_numpy=True)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Gera embedding para uma única query."""
    embedding = model.encode([query], convert_to_numpy=True)
    return embedding[0].tolist()