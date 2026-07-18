"""PDF ingestion into a reviewed, editable DOCX intermediate."""

from .pdf import ingest_pdf_job, pdf_inventory

__all__ = ["ingest_pdf_job", "pdf_inventory"]
