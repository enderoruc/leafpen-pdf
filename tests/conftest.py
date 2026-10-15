import pymupdf
import pytest

from leafpen.core import fonts


def make_pdf(pages=1, rotation=0, cropbox=None, text_lines=("Birinci satır ğüşıöç", "İkinci satır burada")):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=400, height=300)
        if cropbox:
            page.set_cropbox(pymupdf.Rect(cropbox))
        page.set_rotation(rotation)
        y = 60
        for line in text_lines:  # upright for the viewer, like a real rotated document
            page.insert_text(pymupdf.Point(40, y) * page.derotation_matrix, line, fontsize=12,
                             rotate=rotation, **fonts.font_args("sans"))
            y += 16
        fonts.fix_space_mapping(doc, page)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_bytes():
    return make_pdf()
