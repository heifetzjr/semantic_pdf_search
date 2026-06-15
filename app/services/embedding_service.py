import os
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

# Troque o modelo aqui se quiser outro
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

model = SentenceTransformer(MODEL_NAME)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Gera embeddings para uma lista de textos."""
    embeddings = model.encode(texts, convert_to_numpy=True)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Gera embedding para uma única query."""
    embedding = model.encode([query], convert_to_numpy=True)
    return embedding[0].tolist()


def get_vector_size() -> int:
    """Retorna a dimensão do vetor do modelo atual."""
    return model.get_sentence_embedding_dimension()
