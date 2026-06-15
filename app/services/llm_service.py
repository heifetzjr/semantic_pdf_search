import os
import time
from dotenv import load_dotenv
from openai import OpenAI, APIError
from langdetect import detect_langs, LangDetectException

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are an assistant that answers ONLY based on the provided CONTEXT.
Rules:
- Always respond in the same language the user used in their question.
- If the answer is not in the context, say you could not find it in the document.
- Do not make up data.
- Be direct and objective.
- Always cite the source (filename and page number) of each piece of information you use.
- If the context contains descriptions of images, charts or tables, use that information too.
"""


def _detect_language(text: str) -> str:
    try:
        lower = text.strip().lower()
        pt_keywords = [
            "qual", "quando", "como", "porque", "por que", "onde",
            "modelo", "contrato", "valor", "prazo", "cliente", "quais",
            "quantos", "quanto", "quem", "pode", "existe", "tem", "são",
            "foi", "será", "tinha", "preciso", "quero", "mostre",
        ]
        if any(k in lower for k in pt_keywords):
            return "pt"

        langs = detect_langs(text.strip())
        best  = langs[0]

        if best.prob < 0.80:
            return "pt"

        return best.lang

    except LangDetectException:
        return "pt"


def _build_context(results: list[dict]) -> str:
    """
    Monta o contexto com referência de arquivo e página para cada trecho.
    """
    parts = []
    for i, r in enumerate(results, start=1):
        meta        = r["metadata"]
        txt         = meta.get("text", "")
        filename    = meta.get("filename", "desconhecido")
        page_number = meta.get("page_number", "?")
        chunk_type  = meta.get("chunk_type", "text")

        if chunk_type == "image":
            label = f"[Imagem | arquivo: {filename} | página: {page_number}]"
        else:
            label = f"[Trecho {i} | arquivo: {filename} | página: {page_number}]"

        parts.append(f"{label}\n{txt}\n")

    return "\n\n".join(parts)


def answer_with_rag(query: str, results: list[dict]) -> str:
    language      = _detect_language(query)
    LANG_MAP      = {
        "en":    "English",
        "pt":    "Portuguese",
        "es":    "Spanish",
        "fr":    "French",
        "de":    "German",
        "it":    "Italian",
        "zh-cn": "Chinese",
        "ja":    "Japanese",
        "ko":    "Korean",
        "ru":    "Russian",
        "ar":    "Arabic",
    }
    language_name = LANG_MAP.get(language, "Portuguese")
    context       = _build_context(results)

    user_prompt = f"""
You will answer a question using ONLY the information in the CONTEXT.

USER QUESTION:
{query}

DETECTED LANGUAGE (hint only, may be imperfect): {language_name}

CONTEXT (each block shows the source file and page number):
{context}

INSTRUCTIONS:
- Infer the language of the QUESTION directly from its text.
- Answer STRICTLY in the SAME LANGUAGE as the QUESTION.
- For each piece of information used, cite the source in parentheses, like: (arquivo: nome.pdf, página: 3).
- If the answer is not in the CONTEXT, say clearly that you could not find it in the documents.
- Use image descriptions when they are relevant.
"""

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.0,
    )

    return completion.choices[0].message.content.strip()


def generate_summary_and_topics(chunks: list[str], max_retries: int = 3) -> dict:
    sample = "\n\n".join(chunks[:20]) if chunks else ""

    if not sample.strip():
        return {"summary": "", "topics": []}

    attempt = 0
    while attempt < max_retries:
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Você é um assistente que analisa documentos e gera resumos objetivos em português.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Com base nos trechos abaixo, gere:\n"
                            f"1. Um resumo de até 2 frases descrevendo o assunto principal do documento.\n"
                            f"2. Uma lista de até 5 tópicos/palavras-chave separados por vírgula.\n\n"
                            f"Responda EXATAMENTE neste formato:\n"
                            f"RESUMO: <resumo aqui>\n"
                            f"TOPICOS: <topico1>, <topico2>, ...\n\n"
                            f"TRECHOS:\n{sample}"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=300,
            )

            raw     = completion.choices[0].message.content.strip()
            summary = ""
            topics  = []

            for line in raw.splitlines():
                if line.startswith("RESUMO:"):
                    summary = line.replace("RESUMO:", "").strip()
                elif line.startswith("TOPICOS:"):
                    topics = [t.strip() for t in line.replace("TOPICOS:", "").split(",") if t.strip()]

            return {"summary": summary, "topics": topics}

        except APIError as e:
            if hasattr(e, "status") and e.status == 429:
                wait_time = 2 * (attempt + 1)
                print(f"[Summary] ⚠️ Rate limit. Tentando de novo em {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1
                continue
            else:
                print(f"[Summary] ❌ Erro: {e}")
                return {"summary": "", "topics": []}

        except Exception as e:
            print(f"[Summary] ❌ Erro inesperado: {e}")
            return {"summary": "", "topics": []}

    return {"summary": "", "topics": []}
