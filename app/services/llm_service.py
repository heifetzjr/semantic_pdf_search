import os
import json
import time
from openai import OpenAI, APIError
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ════════════════════════════════════════════════════════════════════
# Prompt do sistema
# ════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
You are a specialist assistant for document analysis.

ABSOLUTE RULES:
1. ALWAYS respond in the EXACT same language as the USER'S QUESTION — no exceptions.
   - Question in English   → answer in English
   - Question in Portuguese → answer in Portuguese
   - Question in Italian   → answer in Italian
   - Question in Spanish   → answer in Spanish
   - Question in French    → answer in French
   - Question in German    → answer in German
2. Read ALL provided context before answering.
3. After EACH statement you make, insert the exact citation marker inline: [CIT-1], [CIT-2], etc.
4. Citations go INSIDE the text, right after the sentence they support. Do NOT create a references section at the end.
5. If information comes from multiple chunks, cite all of them: "... [CIT-1][CIT-3]."
6. Be complete — do not omit relevant information found in the context.
7. For numbers, dates, names and values: search the ENTIRE context carefully before saying not found.
8. NEVER invent information not present in the context.
9. If the answer is not in the context, say so clearly in the user's language.
"""


# ════════════════════════════════════════════════════════════════════
# Detecção de idioma via LLM (precisa e confiável)
# ════════════════════════════════════════════════════════════════════

def _detect_language_llm(text: str) -> tuple[str, str]:
    """
    Detecta o idioma da pergunta usando o próprio modelo.
    Retorna (code, name), ex: ("en", "English")
    Fallback para português se falhar.
    """
    prompt = f"""Detect the language of the following text and return a JSON with:
- "code": ISO 639-1 language code (e.g. "pt", "en", "it", "es", "fr", "de")
- "name": full language name in English (e.g. "Portuguese", "English", "Italian")

Text: "{text[:300]}"

Return ONLY valid JSON, nothing else. Example: {{"code": "en", "name": "English"}}"""

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=30,
            response_format={"type": "json_object"},
        )
        result = json.loads(completion.choices[0].message.content)
        code   = result.get("code", "pt").lower().strip()
        name   = result.get("name", "Portuguese").strip()
        print(f"[LLM] Idioma detectado: {name} ({code})")
        return code, name

    except Exception as e:
        print(f"[LLM] ⚠️ Falha na detecção de idioma: {e}. Usando português.")
        return "pt", "Portuguese"


# ════════════════════════════════════════════════════════════════════
# Monta o contexto com marcadores [CIT-N]
# ════════════════════════════════════════════════════════════════════

def _build_context(results: list[dict]) -> str:
    """
    Monta o bloco de contexto.
    Cada trecho exibe seu marcador [CIT-N] — o modelo DEVE usá-lo inline.
    """
    if not results:
        return "(no chunks found)"

    parts = []
    for idx, r in enumerate(results, start=1):
        meta       = r.get("metadata", {})
        txt        = r.get("document", "").strip()
        filename   = meta.get("filename",    "unknown")
        page       = meta.get("page_number", "?")
        chunk_type = meta.get("chunk_type",  "text")
        score      = r.get("score", 0)

        if not txt:
            continue

        tipo  = "IMAGE" if chunk_type == "image" else "TEXT"
        label = (
            f"[CIT-{idx}] | {tipo} | file: {filename} | "
            f"page: {page} | relevance: {score:.2f}"
        )
        parts.append(f"{label}\n{txt}")

    return "\n\n---\n\n".join(parts)


# ════════════════════════════════════════════════════════════════════
# Resposta com RAG + citações inline [CIT-N]
# ════════════════════════════════════════════════════════════════════

def answer_with_rag(query: str, results: list[dict]) -> str:
    """
    Gera a resposta usando os trechos do Qdrant.
    - Detecta o idioma via LLM (preciso)
    - Instrui o modelo a citar [CIT-N] inline no corpo do texto
    - O frontend substitui [CIT-N] por links clicáveis
    """
    lang_code, lang_name = _detect_language_llm(query)

    context = _build_context(results)

    n_text  = sum(1 for r in results
                  if r.get("metadata", {}).get("chunk_type") == "text")
    n_image = sum(1 for r in results
                  if r.get("metadata", {}).get("chunk_type") == "image")

    user_prompt = f"""QUESTION:
{query}

DETECTED LANGUAGE: {lang_name} (code: {lang_code})
⚠️ YOU MUST RESPOND ENTIRELY IN {lang_name.upper()}. NOT IN ANY OTHER LANGUAGE.

CONTEXT STATISTICS:
- Total chunks: {len(results)}
- Text chunks:  {n_text}
- Image chunks: {n_image}

FULL CONTEXT (read ALL chunks before answering):
{context}

RESPONSE FORMAT RULES:
1. Read ALL {len(results)} chunks above before writing anything.
2. After EACH statement, insert the citation marker of the chunk used: [CIT-1], [CIT-2], etc.
3. Example: "The deadline is 30 days [CIT-1]. The budget is R$ 80,000 [CIT-2]."
4. If one statement is supported by multiple chunks: "... [CIT-1][CIT-3]."
5. Do NOT create a references or sources section at the end.
6. Do NOT invent anything beyond what is in the context.
7. If the answer is not in any chunk, say clearly in {lang_name} that the information was not found.
8. Respond ONLY in {lang_name}. This is mandatory.
"""

    attempts = 0
    while attempts < 5:
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=2000,
            )
            return completion.choices[0].message.content.strip()

        except APIError as e:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            if status == 429:
                wait = 2 ** attempts
                print(f"[LLM] ⚠️ Rate limit. Waiting {wait}s... "
                      f"(attempt {attempts + 1}/5)")
                time.sleep(wait)
                attempts += 1
                continue
            print(f"[LLM] ❌ API error: {e}")
            raise

    return (
        "Could not generate a response at this time. "
        "Please try again in a few seconds."
    )


# ════════════════════════════════════════════════════════════════════
# Resumo e tópicos
# ════════════════════════════════════════════════════════════════════

def generate_summary_and_topics(
    chunks: list[str],
    max_chars: int = 6000,
) -> dict:
    """
    Gera resumo curto + tópicos principais do documento.
    Sempre em português (para exibição na lista de PDFs).
    """
    if not chunks:
        return {"summary": "", "topics": []}

    combined = ""
    for chunk in chunks:
        if len(combined) + len(chunk) > max_chars:
            break
        combined += chunk + "\n\n"

    if not combined.strip():
        return {"summary": "", "topics": []}

    prompt = f"""Analise o texto abaixo e retorne JSON com:
1. "summary": resumo de 2-3 frases em português.
2. "topics": lista de até 6 palavras-chave ou frases curtas em português.

Formato obrigatório:
{{
  "summary": "resumo aqui",
  "topics": ["tópico 1", "tópico 2"]
}}

TEXTO:
{combined[:max_chars]}
"""

    attempts = 0
    while attempts < 5:
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role":    "system",
                        "content": (
                            "You analyze documents and return valid JSON only. "
                            "No explanations, just the JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            result = json.loads(completion.choices[0].message.content)
            return {
                "summary": result.get("summary", ""),
                "topics":  result.get("topics",  []),
            }

        except APIError as e:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            if status == 429:
                wait = 2 ** attempts
                print(f"[Summary] ⚠️ Rate limit. Waiting {wait}s...")
                time.sleep(wait)
                attempts += 1
                continue
            print(f"[Summary] ❌ API error: {e}")
            return {"summary": "", "topics": []}

        except Exception as e:
            print(f"[Summary] ❌ Error: {e}")
            return {"summary": "", "topics": []}

    return {"summary": "", "topics": []}