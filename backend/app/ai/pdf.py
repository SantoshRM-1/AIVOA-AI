import re
from dataclasses import dataclass

import pymupdf


@dataclass
class ExtractedPdf:
    pages: list[dict[str, int | str]]
    text: str


class PdfInputError(ValueError):
    pass


def extract_pdf(data: bytes) -> ExtractedPdf:
    if not data.startswith(b"%PDF-"):
        raise PdfInputError("The uploaded file is not a valid PDF document.")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise PdfInputError("Password-protected PDFs are not supported.")
            pages = [
                {
                    "page_number": index + 1,
                    "text": "\n".join(
                        line
                        for line in (
                            re.sub(r"\s+", " ", raw_line).strip()
                            for raw_line in page.get_text("text").splitlines()
                        )
                        if line
                    ),
                }
                for index, page in enumerate(document)
            ]
    except PdfInputError:
        raise
    except (pymupdf.FileDataError, ValueError, RuntimeError) as exc:
        raise PdfInputError("The PDF could not be opened or read.") from exc

    if not pages or not any(page["text"] for page in pages):
        raise PdfInputError(
            "No selectable text was found in this PDF. Scanned documents are not OCR processed."
        )
    text = "\n\n".join(
        f"[Page {page['page_number']}]\n{page['text']}" for page in pages if page["text"]
    )
    return ExtractedPdf(pages=pages, text=text)
