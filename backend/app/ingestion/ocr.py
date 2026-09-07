from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass

import pytesseract
from app.config import Settings
from app.errors import OCRFailed
from app.ingestion.normalized import NormalizedBlock, table_markdown
from PIL import Image, ImageOps


@dataclass
class OCRResult:
    blocks: list[NormalizedBlock]
    confidence: float | None
    engine: str


class BaseOCRProvider(ABC):
    @abstractmethod
    def recognize(self, image: Image.Image, page: int | None = None) -> OCRResult: ...


class TesseractOCRProvider(BaseOCRProvider):
    def __init__(self, config: Settings):
        self.config = config

    def recognize(self, image: Image.Image, page: int | None = None) -> OCRResult:
        if image.width * image.height > self.config.MAX_IMAGE_PIXELS:
            raise OCRFailed("Image exceeds the configured OCR pixel limit.")
        if min(image.size) < 16:
            raise OCRFailed("Image is too small to contain readable text (minimum side: 16 pixels).")
        image = ImageOps.exif_transpose(image)
        original_width, original_height = image.size
        if "A" in image.getbands():
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image.convert("RGBA"))
            image = background.convert("RGB")
        image = ImageOps.grayscale(image)
        if image.width < 1400:
            ratio = min(3, 1400 / image.width)
            image = image.resize((int(image.width * ratio), int(image.height * ratio)))
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.config.OCR_LANGUAGES,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
                timeout=self.config.OCR_TIMEOUT,
            )
        except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, RuntimeError) as exc:
            raise OCRFailed(
                "Tesseract OCR failed. Verify tesseract and fra/eng language packs; check OCR_TIMEOUT."
            ) from exc
        lines = defaultdict(list)
        confidences = []
        for i, text in enumerate(data["text"]):
            if text.strip() and float(data["conf"][i]) >= 0:
                lines[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(i)
                confidences.append(float(data["conf"][i]))
        blocks = []
        sx, sy = original_width / image.width, original_height / image.height
        for indices in lines.values():
            text = " ".join(data["text"][i] for i in indices)
            left = min(data["left"][i] for i in indices)
            top = min(data["top"][i] for i in indices)
            right = max(data["left"][i] + data["width"][i] for i in indices)
            bottom = max(data["top"][i] + data["height"][i] for i in indices)
            cells = []
            current = []
            last_right = None
            for i in indices:
                if last_right is not None and data["left"][i] - last_right > max(20, data["height"][i] * 1.1):
                    cells.append(" ".join(current))
                    current = []
                current.append(data["text"][i])
                last_right = data["left"][i] + data["width"][i]
            if current:
                cells.append(" ".join(current))
            blocks.append(
                NormalizedBlock(
                    type="OCR",
                    text=text,
                    page=page,
                    bbox=[left * sx, top * sy, right * sx, bottom * sy],
                    metadata={
                        "ocr_engine": "tesseract",
                        "ocr_confidence": sum(float(data["conf"][i]) for i in indices) / len(indices) / 100,
                        "bbox_units": "image_pixels",
                        "ocr_cells": cells,
                    },
                )
            )
        # Consecutive aligned rows with at least two separated cells form an OCR table.
        # Retain all original line blocks when structure cannot be inferred confidently.
        structured = []
        index = 0
        while index < len(blocks):
            count = len(blocks[index].metadata["ocr_cells"])
            end = index + 1
            if count >= 2:
                while end < len(blocks) and len(blocks[end].metadata["ocr_cells"]) == count:
                    end += 1
            if count >= 2 and end - index >= 2:
                group = blocks[index:end]
                rows = [block.metadata["ocr_cells"] for block in group]
                structured.append(
                    NormalizedBlock(
                        type="OCR",
                        text=table_markdown(rows),
                        page=page,
                        table_id=f"ocr-{page or 1}-{index}",
                        bbox=[
                            min(b.bbox[0] for b in group),
                            min(b.bbox[1] for b in group),
                            max(b.bbox[2] for b in group),
                            max(b.bbox[3] for b in group),
                        ],
                        metadata={
                            "rows": rows,
                            "header_rows": 1,
                            "ocr_engine": "tesseract",
                            "bbox_units": "image_pixels",
                            "ocr_confidence": sum(b.metadata["ocr_confidence"] for b in group) / len(group),
                        },
                    )
                )
                index = end
            else:
                structured.append(blocks[index])
                index += 1
        return OCRResult(
            structured, sum(confidences) / len(confidences) / 100 if confidences else None, "tesseract"
        )
