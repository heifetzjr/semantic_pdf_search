import base64
import os
import time
from typing import List, Dict
from openai import OpenAI, APIError
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _encode_bytes_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _get_mime_from_ext(ext: str) -> str:
    mime_map = {
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "gif":  "image/gif",
        "webp": "image/webp",
    }
    return mime_map.get(ext.lower(), "image/png")


def _describe_image_once(img_info: dict) -> str:
    image_bytes = img_info.get("image_bytes", b"")
    image_ext   = img_info.get("image_ext", "png")
    image_name  = img_info.get("image_name", "imagem")

    base64_image = _encode_bytes_to_base64(image_bytes)
    mime_type    = _get_mime_from_ext(image_ext)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Descreva esta imagem de forma detalhada e objetiva em português. "
                            "Foque em dados, gráficos, tabelas, esquemas ou qualquer informação "
                            "visual útil para responder perguntas sobre o documento. "
                            "Se for gráfico, descreva valores e tendências. "
                            "Se for tabela, descreva os dados. "
                            "Se for figura ou diagrama, descreva os elementos e relações."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url":    f"data:{mime_type};base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        temperature=0.0,
        max_tokens=1000,
    )

    return completion.choices[0].message.content.strip()


def describe_image(img_info: dict, max_retries: int = 3) -> dict | None:
    """
    Descreve uma única imagem a partir dos bytes.
    Faz retry em caso de erro 429 (rate limit).
    """
    image_bytes = img_info.get("image_bytes", b"")
    image_name  = img_info.get("image_name", "imagem")

    if len(image_bytes) < 1024:
        print(f"[ImageCaption] Ignorando imagem pequena: {image_name}")
        return None

    attempt = 0
    while attempt < max_retries:
        try:
            caption = _describe_image_once(img_info)
            print(f"[ImageCaption] ✅ Descrita: {image_name}")
            return {**img_info, "caption": caption}

        except APIError as e:
            # Erro de rate limit
            if hasattr(e, "status") and e.status == 429:
                wait_time = 2 * (attempt + 1)
                print(f"[ImageCaption] ⚠️ Rate limit ao descrever {image_name}. Tentando de novo em {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1
                continue
            else:
                print(f"[ImageCaption] ❌ Erro em {image_name}: {e}")
                return None

        except Exception as e:
            print(f"[ImageCaption] ❌ Erro inesperado em {image_name}: {e}")
            return None

    print(f"[ImageCaption] ❌ Falha após {max_retries} tentativas em {image_name}")
    return None


def describe_images_bulk(images: List[Dict], max_workers: int = 3) -> List[Dict]:
    """
    Descreve todas as imagens em paralelo usando ThreadPoolExecutor.
    max_workers foi reduzido para 3 para diminuir a chance de estourar o limite.
    """
    if not images:
        return []

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(describe_image, img_info): img_info
            for img_info in images
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    results.sort(key=lambda x: x["page_number"])
    return results