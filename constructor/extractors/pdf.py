"""Vector PDF: the first page rendered as the plan, and its words with positions as label elements.

A minimal step: no PDF-specific templates yet (door and finish schedules are build step 5), so
the drawing opens and shows, and questions answer only where a template fits; `covers` is empty
and there are no whole-image counts, so counts are "can't answer", never 0.
"""

from __future__ import annotations

from pathlib import Path

from ..schema import Drawing, Element

VERSION = "pdf-0.1"
RENDER_WIDTH = 2400  # pixels for the page image
PLANS_DIR = Path("cache/plans")


def extract(path: Path) -> Drawing:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[0]
        width, height = page.get_width(), page.get_height()
        scale = RENDER_WIDTH / width
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        image_path = PLANS_DIR / f"{path.stem}.png"
        page.render(scale=scale).to_pil().save(image_path)

        elements: list[Element] = []
        text = page.get_textpage()
        for i in range(text.count_rects()):
            left, bottom, right, top = text.get_rect(i)
            words = text.get_text_bounded(left, bottom, right, top).strip()
            if words:
                # PDF points, y up -> page-image pixels, y down.
                bbox = [left * scale, (height - top) * scale, right * scale, (height - bottom) * scale]
                elements.append(Element(id=len(elements) + 1, type="label", source=f"page0:rect{i}", exact=True,
                                        label=words, bbox=[round(v, 1) for v in bbox], page=0))
    finally:
        pdf.close()
    return Drawing(drawing=str(path), kind="pdf", extractor_version=VERSION, units="px",
                   elements=elements, covers=[], plan_image=str(image_path))
