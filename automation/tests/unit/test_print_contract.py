from __future__ import annotations

import unittest
from pathlib import Path

from lxml import etree

from framework.core.models import JobConfig
from framework.core.package import NS
from framework.qa.print_contract import validate_print_contract


class _Package:
    def __init__(self, body: etree._Element, settings: etree._Element):
        self._body = body
        self._settings = settings

    def body(self) -> etree._Element:
        return self._body

    def optional_xml(self, name: str) -> etree._Element | None:
        return self._settings if name == "word/settings.xml" else None


class PrintContractTests(unittest.TestCase):
    def _job(self) -> JobConfig:
        root = Path(__file__).resolve().parents[3]
        return JobConfig(
            manifest_path=root / "Books" / "Class 11" / "Maths" / "job.json",
            job_id="print-contract",
            school_class="11",
            subject="Maths",
            source=root / "Books" / "Class 11" / "Maths" / "Input" / "Maths_11th.pdf",
            template=root / "Book_Template.docx",
            preview_output=root / "unused-preview.docx",
            final_output=root / "unused-final.docx",
            approved_reference=None,
            qa_dir=root / "unused-qa",
            source_type="pdf",
            normalized_source=root / "unused-normalized.docx",
            content_manifest=root / "unused-manifest.json",
            preview_source_pages=2,
            preview_source_page_numbers=(3, 14),
            content_policy="reconstruct_content",
            typography_policy="mapped_pdf_fonts",
            boundary_strategy="explicit",
            pdf_font_map=(
                ("hindi", "Nirmala UI"),
                ("latin", "Arial"),
                ("math", "Cambria Math"),
            ),
            content_page_ranges=((3, 104),),
            expected_page_count=102,
            render_authority="word",
        )

    def _package(self) -> _Package:
        body = etree.fromstring(
            f"""<w:body xmlns:w="{NS['w']}">
            <w:p><w:bookmarkStart w:id="1" w:name="SourcePdfPage003"/>
              <w:r><w:t>one</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>
            <w:p><w:r><w:br w:type="page"/></w:r></w:p>
            <w:p><w:bookmarkStart w:id="2" w:name="SourcePdfPage014"/>
              <w:r><w:t>two</w:t></w:r><w:bookmarkEnd w:id="2"/></w:p>
            <w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
            </w:body>""".encode()
        )
        settings = etree.fromstring(
            (
                f"<w:settings xmlns:w=\"{NS['w']}\">"
                "<w:doNotAutoCompressPictures/>"
                "</w:settings>"
            ).encode()
        )
        return _Package(body, settings)

    def _option_table(self) -> etree._Element:
        return etree.fromstring(
            f"""<w:tbl xmlns:w="{NS['w']}">
            <w:tblPr>
              <w:tblW w:type="dxa" w:w="9220"/>
              <w:tblInd w:type="dxa" w:w="420"/>
              <w:tblLayout w:type="fixed"/>
              <w:tblCellMar>
                <w:top w:type="dxa" w:w="0"/>
                <w:right w:type="dxa" w:w="100"/>
                <w:bottom w:type="dxa" w:w="0"/>
                <w:left w:type="dxa" w:w="80"/>
              </w:tblCellMar>
            </w:tblPr>
            <w:tblGrid><w:gridCol w:w="4700"/><w:gridCol w:w="4520"/></w:tblGrid>
            <w:tr><w:trPr><w:cantSplit/></w:trPr>
              <w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4700"/></w:tcPr>
                <w:p><w:r><w:t>(A) One</w:t></w:r></w:p></w:tc>
              <w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4520"/></w:tcPr>
                <w:p><w:r><w:t>(B) Two</w:t></w:r></w:p></w:tc>
            </w:tr>
            <w:tr><w:trPr><w:cantSplit/></w:trPr>
              <w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4700"/></w:tcPr>
                <w:p><w:r><w:t>(C) Three</w:t></w:r></w:p></w:tc>
              <w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4520"/></w:tcPr>
                <w:p><w:r><w:t>(D) Four</w:t></w:r></w:p></w:tc>
            </w:tr>
            </w:tbl>""".encode()
        )

    def test_accepts_disabled_update_fields_flag(self) -> None:
        package = self._package()
        update = etree.SubElement(
            package._settings,
            f"{{{NS['w']}}}updateFields",
        )
        update.set(f"{{{NS['w']}}}val", "false")
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertTrue(result["passed"], result["errors"])

    def test_rejects_enabled_update_fields_flag(self) -> None:
        package = self._package()
        etree.SubElement(package._settings, f"{{{NS['w']}}}updateFields")
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertIn("Automatic field updating is enabled", result["errors"])

    def test_rejects_missing_picture_compression_lock(self) -> None:
        package = self._package()
        compression = package._settings.find(
            ".//w:doNotAutoCompressPictures",
            NS,
        )
        assert compression is not None
        package._settings.remove(compression)
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertIn(
            "Word automatic picture compression is not explicitly disabled",
            result["errors"],
        )

    def test_checks_every_section_for_a4(self) -> None:
        package = self._package()
        section_break = etree.fromstring(
            f"""<w:p xmlns:w="{NS['w']}"><w:pPr><w:sectPr>
              <w:pgSz w:w="12240" w:h="15840"/>
            </w:sectPr></w:pPr></w:p>""".encode()
        )
        package.body().insert(-1, section_break)
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertTrue(
            any("section 1 is not A4" in error for error in result["errors"])
        )

    def test_source_page_count_is_locked_to_configured_sequence(self) -> None:
        result = validate_print_contract(
            self._job(), self._package(), stage="preview", source_pages=1
        )
        self.assertTrue(
            any("Selected source-page count" in error for error in result["errors"])
        )

    def test_accepts_exact_option_table_geometry(self) -> None:
        package = self._package()
        package.body().insert(-1, self._option_table())
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertTrue(result["passed"], result["errors"])

    def test_rejects_duplicate_option_label_and_cell_width_drift(self) -> None:
        package = self._package()
        table = self._option_table()
        width = table.find(".//w:tc/w:tcPr/w:tcW", NS)
        assert width is not None
        width.set(f"{{{NS['w']}}}w", "4000")
        labels = table.findall(".//w:t", NS)
        labels[-1].text = "(A) Four"
        package.body().insert(-1, table)
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertTrue(
            any("labels A-D exactly once" in error for error in result["errors"])
        )
        self.assertTrue(
            any("width does not match" in error for error in result["errors"])
        )

    def test_accepts_source_locked_a4_preview(self) -> None:
        result = validate_print_contract(
            self._job(), self._package(), stage="preview", source_pages=2
        )
        self.assertTrue(result["passed"], result["errors"])

    def test_rejects_tab_leader_answer_lines(self) -> None:
        package = self._package()
        paragraph = etree.fromstring(
            f"""<w:p xmlns:w="{NS['w']}"><w:pPr>
            <w:pBdr><w:bottom w:val="dotted"/></w:pBdr>
            <w:tabs><w:tab w:leader="dot"/></w:tabs>
            </w:pPr></w:p>""".encode()
        )
        package.body().insert(-1, paragraph)
        result = validate_print_contract(
            self._job(), package, stage="preview", source_pages=2
        )
        self.assertFalse(result["passed"])
        self.assertIn("Dotted answer lines also use tab leaders", result["errors"])


if __name__ == "__main__":
    unittest.main()

