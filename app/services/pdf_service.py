import fitz  # PyMuPDF
from typing import List, Dict


def extract_text_and_images(file_bytes: bytes, filename: str) -> dict:
    """
    Extrai texto e imagens diretamente dos bytes do PDF,
    sem salvar nada em disco.
    Retorna:
    {
      "pages": [{"page_number": 1, "text": "..."}],
      "images": [{"page_number": 1, "image_bytes": b"...", "image_ext": "png"}]
    }
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages:  List[Dict] = []
    images: List[Dict] = []

    for page_index, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages.append({
            "page_number": page_index,
            "text":        text or "",
        })

        for img_index, img in enumerate(page.get_images(full=True), start=1):
            xref       = img[0]
            base_image = doc.extract_image(xref)
            images.append({
                "page_number": page_index,
                "image_bytes": base_image["image"],
                "image_ext":   base_image["ext"],
                "image_name":  f"{filename}_p{page_index}_i{img_index}.{base_image['ext']}",
            })

    doc.close()

    return {
        "pages":  pages,
        "images": images,
    }