"""DOCX → PDF for admin ingestion.

Prefer headless LibreOffice (`soffice`) so layout matches Word. On native RunPod
images LibreOffice is often missing; fall back to python-docx text + fpdf2 so
ingest and sermon-library links still work.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_docx_to_pdf(docx_path: Path, pdf_path: Path) -> str:
    """Write ``pdf_path`` from ``docx_path``. Returns ``soffice`` or ``fpdf``."""
    soffice = shutil.which(os.environ.get("SOFFICE_PATH", "soffice"))
    if soffice:
        _convert_with_soffice(soffice, docx_path, pdf_path)
        return "soffice"
    logger.warning("LibreOffice (soffice) not on PATH — converting %s with python-docx/fpdf2", docx_path.name)
    _convert_with_fpdf(docx_path, pdf_path)
    return "fpdf"


def _convert_with_soffice(soffice: str, docx_path: Path, pdf_path: Path) -> None:
    outdir = pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    timeout_s = int(os.environ.get("SOFFICE_TIMEOUT", "300"))
    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip() or 'no output'}"
        )
    produced = outdir / f"{docx_path.stem}.pdf"
    if not produced.exists():
        raise RuntimeError(f"LibreOffice did not create expected PDF at {produced}.")
    if produced.resolve() != pdf_path.resolve():
        produced.replace(pdf_path)


def _convert_with_fpdf(docx_path: Path, pdf_path: Path) -> None:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("python-docx is not installed.") from exc
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fpdf2 is not installed.") from exc

    doc = DocxDocument(str(docx_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    if not paragraphs:
        paragraphs = [docx_path.stem]

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for paragraph in paragraphs:
        line = paragraph.encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 6, line)
        pdf.ln(2)
    pdf.output(str(pdf_path))
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"Fallback PDF writer did not create {pdf_path}")
