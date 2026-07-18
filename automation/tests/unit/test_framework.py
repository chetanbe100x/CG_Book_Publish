from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lxml import etree
from pypdf import PdfWriter

from framework.core.boundary import BoundaryError, selected_body
from framework.core.models import FrameworkError, JobConfig, sha256_file
from framework.core.package import NS, W
from framework.ingest.builder import build_normalized_docx
from framework.ingest.ir import load_book_ir
from framework.ingest.pdf import pdf_inventory


class BoundaryTests(unittest.TestCase):
    def test_selects_through_requested_saved_page_boundary(self) -> None:
        body = etree.fromstring(
            f"""<w:body xmlns:w="{NS['w']}">
            <w:p><w:r><w:t>one</w:t><w:lastRenderedPageBreak/></w:r></w:p>
            <w:p><w:r><w:t>two</w:t><w:lastRenderedPageBreak/></w:r></w:p>
            <w:p><w:r><w:t>three</w:t></w:r></w:p>
            <w:sectPr/>
            </w:body>""".encode()
        )
        selected = selected_body(body, 2)
        text = "".join(selected.xpath(".//w:t/text()", namespaces=NS))
        self.assertEqual(text, "onetwo")
        self.assertEqual(len(selected.findall(".//w:lastRenderedPageBreak", NS)), 2)
        self.assertIsNone(selected.find("w:sectPr", NS))

    def test_refuses_unavailable_boundary(self) -> None:
        body = etree.fromstring(f"<w:body xmlns:w=\"{NS['w']}\"><w:p/></w:body>".encode())
        with self.assertRaises(BoundaryError):
            selected_body(body, 7)

    def test_selects_explicitly_delimited_pdf_pages(self) -> None:
        body = etree.fromstring(
            f"""<w:body xmlns:w="{NS['w']}">
            <w:p><w:r><w:t>one</w:t><w:br w:type="page"/></w:r></w:p>
            <w:p><w:r><w:t>two</w:t><w:br w:type="page"/></w:r></w:p>
            <w:p><w:r><w:t>three</w:t></w:r></w:p>
            <w:sectPr/>
            </w:body>""".encode()
        )
        selected = selected_body(body, 2, strategy="explicit")
        text = "".join(selected.xpath(".//w:t/text()", namespaces=NS))
        self.assertEqual(text, "onetwo")
        self.assertEqual(
            len(selected.findall(".//w:br[@w:type='page']", NS)),
            1,
        )
        full = selected_body(body, 3, strategy="explicit")
        self.assertEqual(
            "".join(full.xpath(".//w:t/text()", namespaces=NS)),
            "onetwothree",
        )


class JobTests(unittest.TestCase):
    def test_registered_job_resolves_paths(self) -> None:
        root = Path(__file__).resolve().parents[3]
        job = JobConfig.load(root / "Books" / "Class 12" / "Maths" / "job.json")
        self.assertEqual(job.job_id, "class-12-maths")
        self.assertTrue(job.source.is_file())
        self.assertTrue(job.template.is_file())

    def test_pdf_job_loads_explicit_ingestion_contract(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            source = temporary / "source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            with source.open("wb") as stream:
                writer.write(stream)
            manifest = temporary / "book_ir.json"
            manifest.write_text("{}", encoding="utf-8")
            job_path = temporary / "job.json"
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": "pdf-test",
                        "class": "11",
                        "subject": "Maths",
                        "source_type": "pdf",
                        "source": str(source),
                        "normalized_source": "normalized.docx",
                        "content_manifest": "book_ir.json",
                        "template": str(root / "Book_Template.docx"),
                        "preview_output": "preview.docx",
                        "final_output": "final.docx",
                        "qa_dir": "QA",
                        "preview_source_pages": 1,
                        "preview_source_page_numbers": [1],
                        "content_policy": "reconstruct_content",
                        "typography_policy": "mapped_pdf_fonts",
                        "boundary_strategy": "explicit",
                        "pdf_font_map": {
                            "hindi": "Nirmala UI",
                            "latin": "Arial",
                            "math": "Cambria Math",
                        },
                    }
                ),
                encoding="utf-8",
            )
            job = JobConfig.load(job_path)
            self.assertEqual(job.source_type, "pdf")
            self.assertEqual(job.preview_page_count, 1)
            self.assertEqual(job.font_for("hindi"), "Nirmala UI")


class PdfIngestionTests(unittest.TestCase):
    def _source_pdf(self, directory: Path) -> Path:
        source = directory / "source.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({"/Title": "Fixture"})
        with source.open("wb") as stream:
            writer.write(stream)
        return source

    def test_pdf_inventory_and_manifest_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            source = self._source_pdf(temporary)
            inventory = pdf_inventory(source)
            self.assertEqual(inventory["page_count"], 1)
            manifest_path = temporary / "book_ir.json"
            value = {
                "schema_version": 1,
                "book_name": "Fixture",
                "scope": "preview",
                "source": {
                    "sha256": sha256_file(source),
                    "page_count": 1,
                },
                "pages": [
                    {
                        "source_page": 1,
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "text": "Verified text",
                                "source_ids": ["source.pdf:p001"],
                                "confidence": "high",
                            }
                        ],
                    }
                ],
            }
            manifest_path.write_text(
                json.dumps(value, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest = load_book_ir(
                manifest_path,
                source_pdf=source,
                expected_pages=(1,),
            )
            self.assertEqual(manifest["pages"][0]["source_page"], 1)
            value["pages"][0]["blocks"][0]["confidence"] = "low"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(FrameworkError):
                load_book_ir(
                    manifest_path,
                    source_pdf=source,
                    expected_pages=(1,),
                )

    def test_builds_explicitly_delimited_normalized_docx(self) -> None:
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            source = self._source_pdf(temporary)
            manifest_path = temporary / "book_ir.json"
            manifest_path.write_text("{}", encoding="utf-8")
            job = JobConfig(
                manifest_path=temporary / "job.json",
                job_id="builder-test",
                school_class="11",
                subject="Maths",
                source=source,
                template=root / "Book_Template.docx",
                preview_output=temporary / "preview.docx",
                final_output=temporary / "final.docx",
                approved_reference=None,
                qa_dir=temporary / "QA",
                source_type="pdf",
                normalized_source=temporary / "normalized.docx",
                content_manifest=manifest_path,
                preview_source_pages=2,
                preview_source_page_numbers=(1, 2),
                content_policy="reconstruct_content",
                typography_policy="mapped_pdf_fonts",
                boundary_strategy="explicit",
                pdf_font_map=(
                    ("hindi", "Nirmala UI"),
                    ("latin", "Arial"),
                    ("math", "Cambria Math"),
                ),
            )
            manifest = {
                "book_name": "Fixture",
                "pages": [
                    {
                        "source_page": 1,
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "text": "Page one",
                                "source_ids": ["source.pdf:p001"],
                            },
                            {
                                "kind": "answer_lines",
                                "count": 2,
                                "spacing_points": 17,
                                "source_ids": ["source.pdf:p001"],
                            },
                            {
                                "kind": "options",
                                "columns": 2,
                                "items": [
                                    {"label": "A", "text": "one", "language": "latin"},
                                    {"label": "B", "text": "two", "language": "latin"},
                                ],
                                "source_ids": ["source.pdf:p001"],
                            },
                        ],
                    },
                    {
                        "source_page": 2,
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "text": "Page two",
                                "source_ids": ["source.pdf:p002"],
                            }
                        ],
                    },
                ],
            }
            result = build_normalized_docx(job, manifest, job.normalized_source)
            self.assertEqual(result["page_count"], 2)
            body = etree.fromstring(
                __import__("zipfile").ZipFile(job.normalized_source).read(
                    "word/document.xml"
                )
            )
            self.assertEqual(
                len(body.findall(".//w:br[@w:type='page']", NS)),
                1,
            )
            widths = [
                cell.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w")
                for cell in body.findall(".//w:tc/w:tcPr/w:tcW", NS)
            ]
            self.assertIn("4320", widths)
            self.assertEqual(
                len(body.findall(".//w:pBdr/w:bottom", NS)),
                2,
            )


class GoldenHashTests(unittest.TestCase):
    def test_protected_root_hashes(self) -> None:
        project = Path(__file__).resolve().parents[3]
        expected = {
            "12 CLASS MATHS.docx": "0E01F2BD42A52D6D9E5AF2E9B3E6B2270192C42F8B64B84534A0CCF0CC72A8E5",
            "Book_Template.docx": "FD6B76A7975CD3D72DEC61DD16511D3686A588E617B65090E936BCFBC9AA5261",
            "12 CLASS MATHS - Book Template.docx": "20397184A52E50C435AC7067DFCFED47E9A22BD7D4FD1A14C4DF8742C2B1DAAA",
        }
        for name, digest in expected.items():
            self.assertEqual(sha256_file(project / name), digest)


if __name__ == "__main__":
    unittest.main()
