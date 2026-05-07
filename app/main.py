from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import uuid
import json

from app.services.pdf_service import extract_text_and_images
from app.services.image_caption_service import describe_images_bulk
from app.services.embedding_service import get_embeddings, embed_query
from app.services.vector_store_service import (
    init_vector_store,
    clear_vector_store,
    add_documents,
    similarity_search,
    delete_documents_by_file,
)
from app.services.llm_service import answer_with_rag, generate_summary_and_topics

app = FastAPI(title="Busca Semântica em PDFs")

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

HISTORY_FILE = Path("history.json")

vector_store  = init_vector_store(persist_directory="chromadb")
upload_status: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history: list[dict]):
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ── Processamento em background ───────────────────────────────────────

def process_pdf_background(file_id: str, file_bytes: bytes, filename: str):
    """
    Processa o PDF a partir dos bytes (sem salvar em disco):
    extrai texto e imagens, descreve imagens, gera embeddings,
    indexa no Chroma e salva só os metadados no histórico.
    """
    upload_status[file_id] = {
        "status":  "processando",
        "message": "Extraindo texto e imagens do PDF...",
    }

    try:
        # 1. Extrai texto e imagens dos bytes
        print(f"[Upload] Extraindo conteúdo de '{filename}'...")
        extracted = extract_text_and_images(file_bytes, filename)
        pages     = extracted["pages"]
        images    = extracted["images"]

        print(f"[Upload] {len(pages)} página(s) | {len(images)} imagem(ns) encontrada(s).")

        all_text = "\n\n".join(p["text"] for p in pages if p["text"].strip())

        if not all_text.strip() and not images:
            upload_status[file_id] = {
                "status":  "erro",
                "message": f"Não foi possível extrair conteúdo de '{filename}'.",
            }
            return

        # 2. Descreve imagens em paralelo (a partir dos bytes, sem salvar)
        described_images = []
        if images:
            upload_status[file_id]["message"] = (
                f"Descrevendo {len(images)} imagem(ns) via IA..."
            )
            print(f"[Upload] Descrevendo {len(images)} imagem(ns)...")
            described_images = describe_images_bulk(images)
            print(f"[Upload] {len(described_images)} imagem(ns) descritas.")

        # 3. Monta chunks (texto + descrições de imagens)
        upload_status[file_id]["message"] = "Preparando trechos para indexação..."

        chunks:      list[str] = []
        chunk_types: list[str] = []

        if all_text.strip():
            text_chunks = [c.strip() for c in all_text.split("\n\n") if c.strip()]
            chunks.extend(text_chunks)
            chunk_types.extend(["text"] * len(text_chunks))

        for img in described_images:
            chunks.append(f"[Imagem na página {img['page_number']}]\n{img['caption']}")
            chunk_types.append("image")

        if not chunks:
            upload_status[file_id] = {
                "status":  "erro",
                "message": f"Não foi possível gerar conteúdo para indexar em '{filename}'.",
            }
            return

        print(f"[Upload] Total de chunks: {len(chunks)}.")

        # 4. Gera resumo e tópicos do PDF
        upload_status[file_id]["message"] = "Gerando resumo e tópicos do documento..."
        text_only_chunks = [c for c, t in zip(chunks, chunk_types) if t == "text"]
        meta_doc         = generate_summary_and_topics(text_only_chunks)
        print(f"[Upload] Resumo: {meta_doc['summary']}")
        print(f"[Upload] Tópicos: {meta_doc['topics']}")

        # 5. Embeddings
        upload_status[file_id]["message"] = (
            f"Gerando embeddings para {len(chunks)} trechos..."
        )
        print(f"[Upload] Gerando embeddings...")
        embeddings = get_embeddings(chunks)
        print(f"[Upload] Embeddings gerados.")

        # 6. Indexa no ChromaDB
        upload_status[file_id]["message"] = "Indexando no banco vetorial..."
        print(f"[Upload] Indexando no ChromaDB...")

        docs_metadata = [
            {
                "file_id":     file_id,
                "filename":    filename,
                "chunk_index": i,
                "chunk_type":  chunk_types[i],
                "text":        chunk,
            }
            for i, chunk in enumerate(chunks)
        ]
        add_documents(vector_store, embeddings, docs_metadata)
        print(f"[Upload] Indexação concluída.")

        # 7. Atualiza histórico (só metadados, sem path nem imagens)
        n_text  = chunk_types.count("text")
        n_image = chunk_types.count("image")

        history = load_history()
        history.append({
            "file_id":      file_id,
            "filename":     filename,
            "chunks":       len(chunks),
            "text_chunks":  n_text,
            "image_chunks": n_image,
            "summary":      meta_doc["summary"],
            "topics":       meta_doc["topics"],
        })
        save_history(history)

        upload_status[file_id] = {
            "status":       "concluido",
            "message":      (
                f"✅ '{filename}' processado! "
                f"{n_text} trechos de texto e {n_image} imagem(ns) indexados."
            ),
            "file_id":      file_id,
            "filename":     filename,
            "chunks":       len(chunks),
            "text_chunks":  n_text,
            "image_chunks": n_image,
            "summary":      meta_doc["summary"],
            "topics":       meta_doc["topics"],
        }
        print(f"[Upload] ✅ Concluído: '{filename}'.")

    except Exception as e:
        upload_status[file_id] = {
            "status":  "erro",
            "message": f"Erro ao processar '{filename}': {str(e)}",
        }
        print(f"[Upload] ❌ Erro em '{filename}': {e}")


# ── Rotas ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Lê o PDF em memória e dispara o processamento em background.
    Não salva nada em disco.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    history = load_history()
    if any(p["filename"] == file.filename for p in history):
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}' já foi enviado. Remova-o antes de reenviar.",
        )

    # Lê os bytes do PDF em memória (sem salvar em disco)
    file_bytes = await file.read()
    file_id    = uuid.uuid4().hex

    upload_status[file_id] = {
        "status":  "processando",
        "message": "PDF recebido. Iniciando processamento...",
    }

    background_tasks.add_task(
        process_pdf_background,
        file_id,
        file_bytes,
        file.filename,
    )

    return JSONResponse({
        "message":  f"📥 '{file.filename}' recebido! Processando em background...",
        "file_id":  file_id,
        "filename": file.filename,
        "status":   "processando",
    })


@app.get("/upload-status/{file_id}")
async def get_upload_status(file_id: str):
    """Retorna o status atual do processamento de um PDF."""
    status = upload_status.get(file_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status não encontrado.")
    return JSONResponse(status)


@app.get("/pdfs")
async def list_pdfs():
    """Lista todos os PDFs indexados com nome, resumo e tópicos."""
    return JSONResponse({"pdfs": load_history()})


@app.delete("/delete-pdf/{file_id}")
async def delete_pdf(file_id: str):
    """Remove um PDF do banco vetorial e do histórico."""
    history = load_history()
    item    = next((p for p in history if p["file_id"] == file_id), None)

    if not item:
        raise HTTPException(status_code=404, detail="PDF não encontrado.")

    # Remove vetores do ChromaDB
    delete_documents_by_file(vector_store, file_id)
    print(f"[Delete] Vetores removidos para file_id={file_id}")

    # Remove do status e do histórico
    upload_status.pop(file_id, None)
    history = [p for p in history if p["file_id"] != file_id]
    save_history(history)

    print(f"[Delete] ✅ '{item['filename']}' removido do banco.")

    return JSONResponse({
        "message": f"🗑️ '{item['filename']}' removido do banco com sucesso.",
    })


@app.delete("/clear-all")
async def clear_all():
    """Limpa todo o banco vetorial e o histórico."""
    global vector_store

    vector_store = clear_vector_store(persist_directory="chromadb")
    upload_status.clear()
    save_history([])

    print(f"[ClearAll] ✅ Banco vetorial e histórico limpos.")

    return JSONResponse({
        "message": "🧹 Banco vetorial limpo com sucesso.",
    })


@app.post("/search")
async def semantic_search(
    request: Request,
    query: str  = Form(...),
    top_k: int  = Form(10),
):
    """
    Busca semântica em todos os PDFs indexados.
    Responde no mesmo idioma da pergunta.
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="A consulta não pode ser vazia.")

    if not load_history():
        raise HTTPException(status_code=400, detail="Nenhum PDF foi enviado ainda.")

    query_emb = embed_query(query)
    results   = similarity_search(vector_store, query_emb, top_k=top_k)

    if not results:
        return JSONResponse({
            "query":  query,
            "answer": "Não encontrei informações relevantes nos documentos.",
        })

    answer = answer_with_rag(query, results)

    return JSONResponse({
        "query":  query,
        "answer": answer,
    })