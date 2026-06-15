import base64
import os
import time
from typing import List, Dict
from openai import OpenAI, APIError
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _encode_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def _mime(ext: str) -> str:
    return {
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "gif":  "image/gif",
        "webp": "image/webp",
    }.get(ext.lower(), "image/png")


def _describe_one(img: dict, attempt: int = 0) -> dict | None:
    """
    Recebe um dict com image_bytes, image_ext, page_number, image_name.
    Retorna o mesmo dict + campo 'caption'. None se falhar.
    """
    if len(img.get("image_bytes", b"")) < 1024:
        print(f"[ImageCaption] Ignorando imagem pequena: {img.get('image_name')}")
        return None

    base64_img = _encode_bytes(img["image_bytes"])
    mime_type  = _mime(img["image_ext"])

    try:
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
                                "Inclua dados, gráficos, tabelas ou qualquer informação visual "
                                "que possa ser útil para responder perguntas sobre o documento."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url":    f"data:{mime_type};base64,{base64_img}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            temperature=0.0,
            max_tokens=1000,
        )
        caption = completion.choices[0].message.content.strip()
        print(f"[ImageCaption] ✅ Descrita: {img.get('image_name')}")
        return {**img, "caption": caption}

    except APIError as e:
        if hasattr(e, "status") and e.status == 429 and attempt < 3:
            wait = 2 * (attempt + 1)
            print(f"[ImageCaption] ⚠️ Rate limit em {img.get('image_name')}. Aguardando {wait}s...")
            time.sleep(wait)
            return _describe_one(img, attempt + 1)
        print(f"[ImageCaption] ❌ Erro em {img.get('image_name')}: {e}")
        return None

    except Exception as e:
        print(f"[ImageCaption] ❌ Erro inesperado em {img.get('image_name')}: {e}")
        return None


def describe_images_bulk(images: List[Dict], max_workers: int = 3) -> List[Dict]:
    """
    Processa as imagens em paralelo e devolve apenas as descritas com sucesso.
    """
    if not images:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_describe_one, img): img for img in images}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x["page_number"])
    return results