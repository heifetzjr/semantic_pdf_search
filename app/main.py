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
    get_client,
)
from app.services.llm_service import answer_with_rag, generate_summary_and_topics

# ── Configuração da aplicação ────────────────────────────────────────
app = FastAPI(title="Busca Semântica em PDFs")

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

HISTORY_FILE = Path("history.json")
I18N_DIR     = Path("app/static/i18n")

# ── Inicializa o banco vetorial (singleton) ──────────────────────────
init_vector_store()

# ── Estado de uploads em andamento ──────────────────────────────────
upload_status: dict[str, dict] = {}


# ════════════════════════════════════════════════════════════════════
# Helpers de histórico
# ════════════════════════════════════════════════════════════════════

def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history: list[dict]):
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════════
# Processamento de PDF em background
# ════════════════════════════════════════════════════════════════════

def process_pdf_background(file_id: str, file_bytes: bytes, filename: str):
    """
    Pipeline completo de indexação de um PDF:
    1. Extrai texto e imagens
    2. Descreve imagens via IA
    3. Gera resumo e tópicos
    4. Gera embeddings
    5. Indexa no Qdrant
    6. Salva no histórico
    """
    upload_status[file_id] = {
        "status":  "processando",
        "message": f"Extraindo texto e imagens de '{filename}'...",
    }

    try:
        # 1. Extração
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

        # 2. Descrição de imagens
        described_images = []
        if images:
            upload_status[file_id]["message"] = (
                f"Descrevendo {len(images)} imagem(ns) via IA..."
            )
            print(f"[Upload] Descrevendo {len(images)} imagem(ns)...")
            described_images = describe_images_bulk(images)
            print(f"[Upload] {len(described_images)} imagem(ns) descritas.")

        # 3. Monta chunks com page_number
        upload_status[file_id]["message"] = "Preparando trechos para indexação..."

        chunks:       list[str] = []
        chunk_types:  list[str] = []
        page_numbers: list[int] = []

        # Chunks de texto — preserva número da página
        for page in pages:
            if not page["text"].strip():
                continue
            page_chunks = [c.strip() for c in page["text"].split("\n\n") if c.strip()]
            for chunk in page_chunks:
                chunks.append(chunk)
                chunk_types.append("text")
                page_numbers.append(page["page_number"])

        # Chunks de imagens
        for img in described_images:
            caption_text = f"[Imagem na página {img['page_number']}]\n{img['caption']}"
            chunks.append(caption_text)
            chunk_types.append("image")
            page_numbers.append(img["page_number"])

        if not chunks:
            upload_status[file_id] = {
                "status":  "erro",
                "message": f"Não foi possível gerar conteúdo indexável para '{filename}'.",
            }
            return

        print(f"[Upload] Total de chunks: {len(chunks)}.")

        # 4. Resumo e tópicos
        upload_status[file_id]["message"] = "Gerando resumo e tópicos..."
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

        # 6. Indexação no Qdrant
        upload_status[file_id]["message"] = "Indexando no banco vetorial..."
        print(f"[Upload] Indexando no Qdrant...")

        docs_metadata = [
            {
                "file_id":     file_id,
                "filename":    filename,
                "chunk_index": i,
                "chunk_type":  chunk_types[i],
                "page_number": page_numbers[i],
                "text":        chunk,
            }
            for i, chunk in enumerate(chunks)
        ]

        add_documents(get_client(), embeddings, docs_metadata)
        print(f"[Upload] Indexação concluída.")

        # 7. Histórico
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


# ════════════════════════════════════════════════════════════════════
# Rotas — interface
# ════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ════════════════════════════════════════════════════════════════════
# Rotas — i18n
# ════════════════════════════════════════════════════════════════════

@app.get("/languages")
async def list_languages():
    """
    Lê dinamicamente a pasta i18n/ e devolve a lista de idiomas disponíveis.
    O arquivo _labels.json é excluído da lista (é apenas configuração visual).
    Qualquer novo .json adicionado à pasta aparece automaticamente.
    """
    if not I18N_DIR.exists():
        return JSONResponse({"languages": []})

    languages = []
    for f in sorted(I18N_DIR.glob("*.json")):
        code = f.stem
        if code == "_labels":
            continue
        languages.append({"code": code})

    return JSONResponse({"languages": languages})


# ════════════════════════════════════════════════════════════════════
# Rotas — upload
# ════════════════════════════════════════════════════════════════════

@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Apenas arquivos PDF são aceitos.",
        )

    history = load_history()
    if any(p["filename"] == file.filename for p in history):
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}' já foi enviado. Remova-o antes de reenviar.",
        )

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
    status = upload_status.get(file_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status não encontrado.")
    return JSONResponse(status)


# ════════════════════════════════════════════════════════════════════
# Rotas — listagem e remoção de PDFs
# ════════════════════════════════════════════════════════════════════

@app.get("/pdfs")
async def list_pdfs():
    return JSONResponse({"pdfs": load_history()})


@app.delete("/delete-pdf/{file_id}")
async def delete_pdf(file_id: str):
    history = load_history()
    item    = next((p for p in history if p["file_id"] == file_id), None)

    if not item:
        raise HTTPException(status_code=404, detail="PDF não encontrado.")

    delete_documents_by_file(get_client(), file_id)
    upload_status.pop(file_id, None)

    history = [p for p in history if p["file_id"] != file_id]
    save_history(history)

    print(f"[Delete] ✅ '{item['filename']}' removido do Qdrant.")

    return JSONResponse({
        "message": f"🗑️ '{item['filename']}' removido com sucesso.",
    })


@app.delete("/clear-all")
async def clear_all():
    """
    Limpa toda a coleção do Qdrant e reinicia o histórico.
    Usa o singleton — NÃO cria nova instância do cliente.
    """
    clear_vector_store()
    upload_status.clear()
    save_history([])

    print("[ClearAll] ✅ Banco vetorial e histórico limpos.")

    return JSONResponse({
        "message": "🧹 Banco vetorial limpo com sucesso.",
    })


# ════════════════════════════════════════════════════════════════════
# Rotas — busca semântica
# ════════════════════════════════════════════════════════════════════

@app.post("/search")
async def semantic_search(
    request: Request,
    query: str = Form(...),
    top_k: int = Form(10),
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="A consulta não pode ser vazia.")

    if not load_history():
        raise HTTPException(
            status_code=400,
            detail="Nenhum PDF foi enviado ainda.",
        )

    query_emb = embed_query(query)
    results   = similarity_search(get_client(), query_emb, top_k=top_k)

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
