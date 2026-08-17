"""Small dependency-free PDF writer for AAP text-and-table reports."""
from __future__ import annotations

import textwrap
from typing import Any, Optional


PAGE_WIDTH = 792
PAGE_HEIGHT = 612
MARGIN = 36
CONTENT_WIDTH = PAGE_WIDTH - (MARGIN * 2)


def pdf_string(value: Any) -> str:
    """Return a PDF-safe WinAnsi literal using only ASCII source bytes."""
    encoded = str(value).encode("cp1252", errors="replace")
    escaped = []
    for byte in encoded:
        if byte in (40, 41, 92):
            escaped.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")
    return "".join(escaped)


class StandardLibraryPdf:
    """Tiny PDF 1.4 writer for text-and-table reports."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = []
        self.current: list[str] = []
        self.y = PAGE_HEIGHT - MARGIN
        self.new_page()

    def new_page(self) -> None:
        if self.current:
            self.pages.append(self.current)
        self.current = []
        self.y = PAGE_HEIGHT - MARGIN

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        size: float = 9,
        bold: bool = False,
    ) -> None:
        font = "F2" if bold else "F1"
        self.current.append(
            f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({pdf_string(value)}) Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.current.append(
            f"0.70 G 0.50 w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S 0 G"
        )

    def rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill_gray: Optional[float] = None,
    ) -> None:
        if fill_gray is not None:
            self.current.append(
                f"{fill_gray:.2f} g {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g"
            )
        self.current.append(
            f"0.70 G 0.50 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S 0 G"
        )

    def finish(self) -> bytes:
        if self.current:
            self.pages.append(self.current)
            self.current = []
        page_count = len(self.pages)
        objects: list[bytes] = [b""] * (5 + page_count * 2)
        page_ids = [5 + index * 2 for index in range(page_count)]
        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[2] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")
        )
        objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

        for index, commands in enumerate(self.pages):
            page_id = page_ids[index]
            content_id = page_id + 1
            footer = (
                f"BT /F1 8.00 Tf 1 0 0 1 {PAGE_WIDTH / 2 - 22:.2f} 18.00 Tm "
                f"(Page {index + 1} of {page_count}) Tj ET"
            )
            stream = ("\n".join(commands + [footer]) + "\n").encode("ascii")
            objects[page_id] = (
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
            objects[content_id] = (
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"endstream"
            )

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id in range(1, len(objects)):
            offsets.append(len(output))
            output.extend(f"{object_id} 0 obj\n".encode("ascii"))
            output.extend(objects[object_id])
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(output)


def wrapped_lines(value: Any, width: float, font_size: float = 9) -> list[str]:
    characters = max(1, int((width - 10) / (font_size * 0.52)))
    lines: list[str] = []
    for paragraph in str(value).replace("\t", " ").splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=characters,
                break_long_words=True,
                break_on_hyphens=True,
            )
            or [""]
        )
    return lines


def page_heading(
    document: StandardLibraryPdf,
    report_title: str,
    continuation: str = "",
) -> None:
    document.text(MARGIN, document.y, report_title, 16, True)
    if continuation:
        document.text(MARGIN + 360, document.y + 1, continuation, 9)
    document.y -= 14
    document.line(MARGIN, document.y, PAGE_WIDTH - MARGIN, document.y)
    document.y -= 18


def table(
    document: StandardLibraryPdf,
    report_title: str,
    section_title: str,
    headers: list[str],
    rows: list[list[Any]],
    widths: list[float],
) -> None:
    row_number = 0

    def draw_header() -> None:
        x = MARGIN
        height = 24
        for header, width in zip(headers, widths):
            document.rectangle(x, document.y - height, width, height, 0.90)
            document.text(x + 5, document.y - 15, header, 8.5, True)
            x += width
        document.y -= height

    if document.y < 105:
        document.new_page()
        page_heading(document, report_title, f"{section_title} - continued")
    document.text(MARGIN, document.y, section_title, 12, True)
    document.y -= 16
    draw_header()

    if not rows:
        document.text(MARGIN + 5, document.y - 16, "No matching records were found.", 9)
        document.y -= 28
        return

    for row in rows:
        wrapped = [
            wrapped_lines(value, width, 8.5)
            for value, width in zip(row, widths)
        ]
        height = max(24, max(len(lines) for lines in wrapped) * 11 + 8)
        if document.y - height < 34:
            document.new_page()
            page_heading(document, report_title, f"{section_title} - continued")
            draw_header()
        x = MARGIN
        fill = 0.97 if row_number % 2 else None
        for lines, width in zip(wrapped, widths):
            document.rectangle(x, document.y - height, width, height, fill)
            baseline = document.y - 14
            for line in lines:
                document.text(x + 5, baseline, line, 8.5)
                baseline -= 11
            x += width
        document.y -= height
        row_number += 1
    document.y -= 12
