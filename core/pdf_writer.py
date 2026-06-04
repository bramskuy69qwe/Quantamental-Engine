"""Minimal dependency-free PDF writer (Phase 7.5).

Produces a valid multi-page PDF of monospaced (Courier) text — enough for the
closed-position audit PDF (a paginated text report + a signed-timestamp block).
The project pulls in NO PDF library and an audit export is a compliance artifact
(a faithful text record), not a styled document, so a vendored text writer is the
self-contained choice (operator-chosen, P7.T5).

Scope: ASCII / latin-1 text only (non-latin-1 chars → ``?``); the standard-14
Courier font needs no embedding. Lines are truncated to a safe width and
paginated; byte offsets for the xref table are tracked exactly.
"""
from __future__ import annotations

from typing import List

_PAGE_W = 612      # US Letter, points
_PAGE_H = 792
_MARGIN = 36
_FONT_SIZE = 9
_LEADING = 11
_MAX_CHARS = 100   # Courier 9pt ≈ 5.4pt/char → ~100 chars fit in the text width
_LINES_PER_PAGE = (_PAGE_H - 2 * _MARGIN) // _LEADING   # ~65


def _escape(text: str) -> bytes:
    """Latin-1-encode + escape the PDF string special chars, dropping controls."""
    raw = text.encode("latin-1", "replace")          # non-latin-1 → b'?'
    raw = bytes(b if 32 <= b <= 255 else ord("?") for b in raw)  # strip controls
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content_stream(lines: List[str]) -> bytes:
    body = bytearray()
    body += b"BT\n/F1 %d Tf\n" % _FONT_SIZE
    body += b"%d %d Td\n%d TL\n" % (_MARGIN, _PAGE_H - _MARGIN - _FONT_SIZE, _LEADING)
    for ln in lines:
        body += b"(" + _escape(ln[:_MAX_CHARS]) + b") Tj\nT*\n"
    body += b"ET"
    return bytes(body)


def text_pdf(lines: List[str]) -> bytes:
    """Render ``lines`` to a paginated single-font PDF and return the bytes."""
    pages: List[List[str]] = [
        lines[i:i + _LINES_PER_PAGE]
        for i in range(0, max(len(lines), 1), _LINES_PER_PAGE)
    ]
    n_pages = len(pages)
    # Object numbering: 1=catalog, 2=pages, 3=font, then (page, content) per page.
    page_obj_nums = [4 + 2 * i for i in range(n_pages)]
    content_obj_nums = [5 + 2 * i for i in range(n_pages)]

    objs: List[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")                              # 1
    kids = b" ".join(b"%d 0 R" % p for p in page_obj_nums)
    objs.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % n_pages)   # 2
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")           # 3
    for i, page_lines in enumerate(pages):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (_PAGE_W, _PAGE_H, content_obj_nums[i])
        )
        stream = _content_stream(page_lines)
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")   # binary-marker comment
    offsets: List[int] = []
    for idx, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % idx + body + b"\nendobj\n"

    xref_off = len(out)
    n_obj = len(objs) + 1                                # +1 for the free head (obj 0)
    out += b"xref\n0 %d\n" % n_obj
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % n_obj
    out += b"startxref\n%d\n%%%%EOF" % xref_off
    return bytes(out)
