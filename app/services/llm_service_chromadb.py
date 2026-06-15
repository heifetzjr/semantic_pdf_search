import os
from dotenv import load_dotenv
from openai import OpenAI
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
- When it makes sense, quote excerpts from the context.
- If the context contains descriptions of images, charts or tables, use that information too.
"""


def _detect_language(text: str) -> str:
    """
    Detecta o idioma com heurísticas para não errar português em frases curtas.
    """
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
    parts = []
    for i, r in enumerate(results, start=1):
        txt      = r["metadata"]["text"]
        filename = r["metadata"].get("filename", "desconhecido")
        parts.append(f"[Trecho {i} | arquivo: {filename}]\n{txt}\n")
    return "\n\n".join(parts)


def answer_with_rag(query: str, results: list[dict]) -> str:
    """
    Gera a resposta usando RAG.
    O modelo infere o idioma diretamente do texto da pergunta.
    """
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

CONTEXT (text and image descriptions from the documents):
{context}

INSTRUCTIONS:
- First, infer the language of the QUESTION directly from its text.
- Answer STRICTLY in the SAME LANGUAGE as the QUESTION, regardless of the detected code shown above.
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


import time
from openai import APIError
# ... resto dos imports já existentes ...

def generate_summary_and_topics(chunks: list[str], max_retries: int = 3) -> dict:
    """
    Gera resumo e tópicos do PDF.
    Faz retry em caso de rate limit (429).
    """
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
                print(f"[Summary] ⚠️ Rate limit ao gerar resumo. Tentando de novo em {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1
                continue
            else:
                print(f"[Summary] ❌ Erro ao gerar resumo: {e}")
                return {"summary": "", "topics": []}

        except Exception as e:
            print(f"[Summary] ❌ Erro inesperado ao gerar resumo: {e}")
            return {"summary": "", "topics": []}

    print(f"[Summary] ❌ Falha após {max_retries} tentativas.")
    return {"summary": "", "topics": []}