#!/usr/bin/env python3
"""Generate a sample RFP PDF for testing the upload pipeline.

Usage:
    uv run python scripts/generate_sample_pdf.py
    uv run python scripts/generate_sample_pdf.py --output /tmp/my-sample.pdf
    uv run python scripts/generate_sample_pdf.py --serve  # write to data/raw/

Output is a valid PDF that markitdown[pdf] can convert to Markdown.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _escape_pdf(s: str) -> str:
    """Escape a PDF string literal."""
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


SAMPLE_RFP_CONTENT = """\
# Community Arts Initiative - Grant Application 2026

**Applicant:** Downtown Arts Collective
**Date:** 2026-12-01
**Requested amount:** $8,500

## Programming

Weekly art workshops for teens (ages 13-17), Saturday exhibitions.
Expected participation: 25 teens per session.
We will showcase student work at the end-of-year gallery night.

## Facilities

Need Gallery Space A for workshops and exhibitions.
Requires easels, sinks, and secure storage.
Access needed on weekends and evenings.

## Budget

50% upfront for supplies, 50% upon program completion.
Non-profit status verified (501(c)(3) attached).
Budget includes instructor stipends, materials, and insurance.

GRANT APPLICATION
"""


def generate_sample_pdf(
    output_path: str | Path,
    content: str | None = None,
) -> str:
    """Create a minimal but valid PDF that markitdown can convert.

    The PDF embeds the text content as show-string operations so that
    pdfminer (used by markitdown[pdf]) can extract it.
    """
    content = content or SAMPLE_RFP_CONTENT
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = content.splitlines()
    # Build PDF content stream — one text line per Tj
    stream_lines = ["BT"]
    y = 740
    for line in lines:
        text = line.lstrip("#*").strip()
        if not text:
            y -= 14
            continue
        escaped = _escape_pdf(text)
        stream_lines.append(f"/F1 11 Tf\n50 {y} Td ({escaped}) Tj")
        y -= 16
    stream_lines.append("ET")
    stream_body = "\n".join(stream_lines)
    stream_body_bytes = stream_body.encode("latin-1")

    # Build PDF objects
    objects = []
    # Object 1: Catalog
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
    # Object 2: Pages
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
    # Object 3: Page
    objects.append(
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R\n"
        b"   /Resources << /Font << /F1 5 0 R >> >> >>\n"
        b"endobj"
    )
    # Object 4: Content stream
    obj4 = (
        b"4 0 obj\n"
        b"<< /Length " + str(len(stream_body_bytes)).encode() + b" >>\n"
        b"stream\n" + stream_body_bytes + b"\nendstream\nendobj"
    )
    objects.append(obj4)
    # Object 5: Font
    objects.append(
        b"5 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj"
    )

    # Header
    header = b"%PDF-1.4\n%\xFF\xFF\xFF\xFF\n"

    # Build full body and compute offsets
    body_parts = [header]
    offsets = [0]  # offset 0 is free (object 0)
    for i, obj in enumerate(objects):
        offsets.append(len(b"".join(body_parts)))
        body_parts.append(obj + b"\n")

    body = b"".join(body_parts)
    xref_offset = len(body)

    # xref table
    xref_lines = [b"xref", b"0 6"]
    xref_lines.append(b"0000000000 65535 f \r")
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \r".encode())
    xref = b"\n".join(xref_lines)

    trailer = (
        b"\ntrailer\n"
        b"<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_offset).encode() + b"\n"
        b"%%EOF"
    )

    pdf_bytes = body + xref + trailer
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)

    print(f"PDF sample generado: {output_path} ({output_path.stat().st_size} bytes)")
    return str(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generar PDF de ejemplo para RFP")
    parser.add_argument(
        "--output", "-o",
        default="",
        help="Ruta de salida (por defecto: data/raw/sample-rfp.pdf)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Escribir en data/raw/ para que el servidor lo sirva",
    )
    args = parser.parse_args()

    if args.serve:
        output = Path("data/raw") / "sample-rfp.pdf"
    elif args.output:
        output = Path(args.output)
    else:
        output = Path("/workspaces/dsmora-python-hello-2") / "sample-rfp.pdf"

    path = generate_sample_pdf(output)
    print(f"\n📄 Puedes descargarlo desde: file://{path}")
    print(f"   O súbelo al dashboard en http://localhost:8000")
    print()
    print("── Contenido del RFP ──────────────────────────────")
    print(SAMPLE_RFP_CONTENT)


if __name__ == "__main__":
    main()