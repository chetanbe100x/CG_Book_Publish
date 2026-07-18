from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FrameworkError(RuntimeError):
    """Base error for a deliberately stopped framework operation."""


class IntegrityError(FrameworkError):
    """Raised when a protected file or approval hash no longer matches."""


class UnsupportedFeatureError(FrameworkError):
    """Raised when fidelity cannot be guaranteed for an OOXML feature."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass(frozen=True)
class JobConfig:
    manifest_path: Path
    job_id: str
    school_class: str
    subject: str
    source: Path
    template: Path
    preview_output: Path
    final_output: Path
    approved_reference: Path | None
    qa_dir: Path
    source_type: str = "docx"
    normalized_source: Path | None = None
    content_manifest: Path | None = None
    preview_source_pages: int = 7
    preview_source_page_numbers: tuple[int, ...] = field(default_factory=tuple)
    content_policy: str = "layout_only"
    typography_policy: str = "preserve_source"
    boundary_strategy: str = "saved_rendered"
    pdf_font_map: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    subject_profile: str = "science"
    adapter: str | None = None
    required_fonts: tuple[str, ...] = field(default_factory=tuple)
    layout_reference: Path | None = None
    content_page_ranges: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    first_content_side: str = "recto"
    expected_page_count: int | None = None
    render_authority: str = "libreoffice"
    source_style_policy: str = "source_authority"
    pagination_policy: str = "source_locked"

    @staticmethod
    def load(manifest_path: str | Path) -> "JobConfig":
        manifest = Path(manifest_path).resolve()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        base = manifest.parent

        def resolve(name: str, *, optional: bool = False) -> Path | None:
            raw = data.get(name)
            if raw in (None, "") and optional:
                return None
            if not isinstance(raw, str) or not raw:
                raise FrameworkError(f"Missing job path: {name}")
            candidate = Path(raw)
            return (candidate if candidate.is_absolute() else base / candidate).resolve()

        source = resolve("source")
        assert source is not None
        source_type = str(data.get("source_type", source.suffix.lstrip("."))).casefold()
        normalized_source = resolve("normalized_source", optional=True)
        content_manifest = resolve("content_manifest", optional=True)
        layout_reference = resolve("layout_reference", optional=True)
        page_numbers = tuple(int(v) for v in data.get("preview_source_page_numbers", []))
        page_ranges_value = data.get("content_page_ranges", [])
        if not isinstance(page_ranges_value, list):
            raise FrameworkError("content_page_ranges must be an array")
        page_ranges: list[tuple[int, int]] = []
        for index, value in enumerate(page_ranges_value, start=1):
            if not isinstance(value, list) or len(value) != 2:
                raise FrameworkError(
                    f"content_page_ranges item {index} must contain [start, end]"
                )
            page_ranges.append((int(value[0]), int(value[1])))
        font_map_value = data.get("pdf_font_map", {})
        if not isinstance(font_map_value, dict):
            raise FrameworkError("pdf_font_map must be an object")

        job = JobConfig(
            manifest_path=manifest,
            job_id=str(data["job_id"]),
            school_class=str(data["class"]),
            subject=str(data["subject"]),
            source=source,
            template=resolve("template"),
            preview_output=resolve("preview_output"),
            final_output=resolve("final_output"),
            approved_reference=resolve("approved_reference", optional=True),
            qa_dir=resolve("qa_dir"),
            source_type=source_type,
            normalized_source=normalized_source,
            content_manifest=content_manifest,
            preview_source_pages=int(data.get("preview_source_pages", 7)),
            preview_source_page_numbers=page_numbers,
            content_policy=str(data.get("content_policy", "layout_only")),
            typography_policy=str(data.get("typography_policy", "preserve_source")),
            boundary_strategy=str(
                data.get(
                    "boundary_strategy",
                    "explicit" if source_type == "pdf" else "saved_rendered",
                )
            ),
            pdf_font_map=tuple(
                sorted((str(name), str(value)) for name, value in font_map_value.items())
            ),
            subject_profile=str(data.get("subject_profile", "science")),
            adapter=data.get("adapter"),
            required_fonts=tuple(str(v) for v in data.get("required_fonts", [])),
            layout_reference=layout_reference,
            content_page_ranges=tuple(page_ranges),
            first_content_side=str(data.get("first_content_side", "recto")),
            expected_page_count=(
                int(data["expected_page_count"])
                if data.get("expected_page_count") is not None
                else None
            ),
            render_authority=str(data.get("render_authority", "libreoffice")),
            source_style_policy=str(data.get("source_style_policy", "source_authority")),
            pagination_policy=str(data.get("pagination_policy", "source_locked")),
        )
        job.validate()
        return job

    def validate(self) -> None:
        if not self.source.is_file():
            raise FrameworkError(f"Source file not found: {self.source}")
        if not self.template.is_file():
            raise FrameworkError(f"Template DOCX not found: {self.template}")
        if self.approved_reference is not None and not self.approved_reference.is_file():
            raise FrameworkError(f"Approved reference not found: {self.approved_reference}")
        if self.layout_reference is not None and not self.layout_reference.is_file():
            raise FrameworkError(f"Layout reference not found: {self.layout_reference}")
        if self.preview_source_pages < 1:
            raise FrameworkError("preview_source_pages must be positive")
        if self.source_type not in {"docx", "pdf"}:
            raise FrameworkError(f"Unsupported source_type: {self.source_type}")
        if self.source.suffix.casefold() != f".{self.source_type}":
            raise FrameworkError(
                f"source_type {self.source_type} does not match source suffix: {self.source}"
            )
        if self.content_policy not in {"layout_only", "reconstruct_content"}:
            raise FrameworkError(f"Unsupported content_policy: {self.content_policy}")
        if self.typography_policy not in {"preserve_source", "mapped_pdf_fonts"}:
            raise FrameworkError(f"Unsupported typography_policy: {self.typography_policy}")
        if self.boundary_strategy not in {"saved_rendered", "explicit"}:
            raise FrameworkError(f"Unsupported boundary_strategy: {self.boundary_strategy}")
        if self.first_content_side not in {"recto", "verso"}:
            raise FrameworkError("first_content_side must be recto or verso")
        if self.render_authority not in {"word", "libreoffice"}:
            raise FrameworkError("render_authority must be word or libreoffice")
        if self.source_style_policy not in {"source_authority", "content_only"}:
            raise FrameworkError(f"Unsupported source_style_policy: {self.source_style_policy}")
        if self.pagination_policy not in {"source_locked", "sample_flow"}:
            raise FrameworkError(f"Unsupported pagination_policy: {self.pagination_policy}")
        if (
            self.source_style_policy == "content_only"
            or self.pagination_policy == "sample_flow"
        ):
            if self.layout_reference is None:
                raise FrameworkError(
                    "layout_reference is required when source_style_policy is content_only "
                    "or pagination_policy is sample_flow"
                )
        if self.expected_page_count is not None and self.expected_page_count < 1:
            raise FrameworkError("expected_page_count must be positive")
        expanded_pages: list[int] = []
        for index, (start, end) in enumerate(self.content_page_ranges, start=1):
            if start < 1 or end < start:
                raise FrameworkError(
                    f"Invalid content_page_ranges item {index}: [{start}, {end}]"
                )
            expanded_pages.extend(range(start, end + 1))
        if len(set(expanded_pages)) != len(expanded_pages):
            raise FrameworkError("content_page_ranges must not overlap")
        if self.expected_page_count is not None and expanded_pages:
            if len(expanded_pages) != self.expected_page_count:
                raise FrameworkError(
                    "expected_page_count does not match content_page_ranges"
                )
        if self.render_authority == "word" and self.source_type == "pdf":
            if not expanded_pages or self.expected_page_count is None:
                raise FrameworkError(
                    "Word-authoritative PDF jobs require content_page_ranges "
                    "and expected_page_count"
                )
        previous_end = 0
        for index, (start, end) in enumerate(self.content_page_ranges, start=1):
            if start <= previous_end:
                raise FrameworkError(
                    "content_page_ranges must be strictly increasing; "
                    f"item {index} starts at {start} after {previous_end}"
                )
            previous_end = end
        if expanded_pages and any(
            value not in set(expanded_pages) for value in self.preview_source_page_numbers
        ):
            raise FrameworkError("Preview pages must be inside content_page_ranges")
        if len(set(self.preview_source_page_numbers)) != len(
            self.preview_source_page_numbers
        ):
            raise FrameworkError("preview_source_page_numbers must be unique")
        if any(value < 1 for value in self.preview_source_page_numbers):
            raise FrameworkError("preview_source_page_numbers must be positive")
        if self.preview_source_page_numbers and (
            len(self.preview_source_page_numbers) != self.preview_source_pages
        ):
            raise FrameworkError(
                "preview_source_pages must match preview_source_page_numbers length"
            )
        if self.source_type == "docx":
            if self.content_policy != "layout_only":
                raise FrameworkError("DOCX sources require layout_only content_policy")
            if self.typography_policy != "preserve_source":
                raise FrameworkError("DOCX sources require preserve_source typography_policy")
        else:
            if self.normalized_source is None:
                raise FrameworkError("PDF jobs require normalized_source")
            if self.content_manifest is None:
                raise FrameworkError("PDF jobs require content_manifest")
            if self.content_policy != "reconstruct_content":
                raise FrameworkError("PDF jobs require reconstruct_content content_policy")
            if self.typography_policy != "mapped_pdf_fonts":
                raise FrameworkError("PDF jobs require mapped_pdf_fonts typography_policy")
            if self.boundary_strategy != "explicit":
                raise FrameworkError("PDF jobs require explicit boundary_strategy")
            if not self.preview_source_page_numbers:
                raise FrameworkError("PDF jobs require preview_source_page_numbers")
            roles = {name for name, _ in self.pdf_font_map}
            missing_roles = {"hindi", "latin", "math"} - roles
            if missing_roles:
                raise FrameworkError(
                    "PDF jobs require font mappings for: "
                    + ", ".join(sorted(missing_roles))
                )
        protected = {self.source, self.template}
        if self.approved_reference is not None:
            protected.add(self.approved_reference)
        if self.layout_reference is not None:
            protected.add(self.layout_reference)
        if self.preview_output in protected or self.final_output in protected:
            raise IntegrityError("Output path collides with a protected input")
        if self.normalized_source is not None and self.normalized_source in protected:
            raise IntegrityError("Normalized source path collides with a protected input")
        if self.content_manifest is not None and self.content_manifest in protected:
            raise IntegrityError("Content manifest path collides with a protected input")
        generated = [self.preview_output, self.final_output]
        if self.normalized_source is not None:
            generated.append(self.normalized_source)
        if self.content_manifest is not None:
            generated.append(self.content_manifest)
        if len(set(generated)) != len(generated):
            raise IntegrityError("Generated artifact paths must be distinct")

    @property
    def composition_source(self) -> Path:
        if self.source_type == "docx":
            return self.source
        assert self.normalized_source is not None
        if not self.normalized_source.is_file():
            raise FrameworkError(
                f"Normalized PDF source has not been generated: {self.normalized_source}"
            )
        return self.normalized_source

    @property
    def preview_page_count(self) -> int:
        if self.preview_source_page_numbers:
            return len(self.preview_source_page_numbers)
        return self.preview_source_pages

    @property
    def content_page_numbers(self) -> tuple[int, ...]:
        return tuple(
            page
            for start, end in self.content_page_ranges
            for page in range(start, end + 1)
        )

    def expected_pages_for_stage(self, stage: str) -> int | None:
        if stage == "preview":
            return self.preview_page_count
        if stage == "final":
            return self.expected_page_count
        if stage == "source":
            return None
        raise FrameworkError(f"Unknown stage: {stage}")

    def font_for(self, role: str) -> str:
        mapping = dict(self.pdf_font_map)
        if role not in mapping:
            raise FrameworkError(f"No PDF font mapping configured for role: {role}")
        return mapping[role]

    @property
    def audit_path(self) -> Path:
        return self.qa_dir / "audit.json"

    @property
    def status_path(self) -> Path:
        return self.qa_dir / "status.json"

    @property
    def report_path(self) -> Path:
        return self.qa_dir / "QA Report.txt"

    @property
    def artifact_path(self) -> Path:
        return self.qa_dir / "artifact.md"

    def render_dir(self, stage: str) -> Path:
        names = {
            "source": "Source Render",
            "preview": "Preview Render",
            "final": "Final Render",
        }
        if stage not in names:
            raise FrameworkError(f"Unknown render stage: {stage}")
        return self.qa_dir / names[stage]

    def docx_for_stage(self, stage: str) -> Path:
        if stage == "source":
            return self.source
        if stage == "preview":
            return self.preview_output
        if stage == "final":
            return self.final_output
        raise FrameworkError(f"Unknown stage: {stage}")


class StatusStore:
    def __init__(self, job: JobConfig):
        self.job = job

    def load(self) -> dict[str, Any]:
        if not self.job.status_path.exists():
            return {
                "job_id": self.job.job_id,
                "state": "initialized",
                "created_at": utc_now(),
                "history": [],
            }
        return json.loads(self.job.status_path.read_text(encoding="utf-8"))

    def transition(self, state: str, **values: Any) -> dict[str, Any]:
        status = self.load()
        status["state"] = state
        status["updated_at"] = utc_now()
        status.update(values)
        status.setdefault("history", []).append(
            {"state": state, "at": status["updated_at"]}
        )
        atomic_json_write(self.job.status_path, status)
        return status

    def require_current_preview_provenance(self) -> dict[str, Any]:
        """Verify that preview QA/approval still refers to current inputs."""
        status = self.load()
        if not self.job.preview_output.is_file():
            raise IntegrityError("Preview file is missing")
        expected_preview = status.get("preview_sha256")
        if not expected_preview:
            raise IntegrityError("Preview provenance is missing; regenerate the preview")
        if sha256_file(self.job.preview_output) != expected_preview:
            raise IntegrityError("Preview changed after generation; rerun preview and QA")

        bindings: list[tuple[str, Path | None]] = [
            ("source", self.job.source),
            ("template", self.job.template),
        ]
        if self.job.layout_reference is not None:
            bindings.append(("layout_reference", self.job.layout_reference))
        if self.job.approved_reference is not None:
            bindings.append(("approved_reference", self.job.approved_reference))
        if self.job.source_type == "pdf":
            bindings.extend(
                [
                    ("normalized_source", self.job.normalized_source),
                    ("content_manifest", self.job.content_manifest),
                ]
            )
        for label, path in bindings:
            expected = status.get(f"{label}_sha256")
            if not expected:
                raise IntegrityError(
                    f"Preview provenance is missing the {label.replace('_', ' ')} hash"
                )
            if path is None or not path.is_file() or sha256_file(path) != expected:
                raise IntegrityError(
                    f"{label.replace('_', ' ').title()} changed after preview generation"
                )
        return status

    def require_approved_preview(self) -> dict[str, Any]:
        status = self.load()
        approved_hash = status.get("approved_preview_sha256")
        if not approved_hash:
            raise IntegrityError("Full conversion requires explicit preview approval")
        if not self.job.preview_output.is_file():
            raise IntegrityError("Approved preview file is missing")
        current_hash = sha256_file(self.job.preview_output)
        if current_hash != approved_hash:
            raise IntegrityError("Preview changed after approval")
        protected_inputs = [("source", self.job.source), ("template", self.job.template)]
        if self.job.layout_reference is not None:
            protected_inputs.append(("layout_reference", self.job.layout_reference))
        for label, path in protected_inputs:
            expected = status.get(f"approved_{label}_sha256")
            if not expected:
                raise IntegrityError(
                    f"Approved preview is missing the {label.replace('_', ' ')} hash"
                )
            if sha256_file(path) != expected:
                raise IntegrityError(f"{label.title()} changed after preview approval")
        if self.job.approved_reference is not None:
            expected_reference = status.get("approved_reference_sha256")
            if not expected_reference:
                raise IntegrityError(
                    "Approved preview is missing the approved reference hash"
                )
            if sha256_file(self.job.approved_reference) != expected_reference:
                raise IntegrityError(
                    "Approved reference changed after preview approval"
                )
        if self.job.source_type == "pdf":
            for label, path in (
                ("normalized_source", self.job.normalized_source),
                ("content_manifest", self.job.content_manifest),
            ):
                expected = status.get(f"approved_{label}_sha256")
                if not expected:
                    raise IntegrityError(
                        "Approved preview is missing the "
                        f"{label.replace('_', ' ')} hash"
                    )
                if path is None or not path.is_file() or sha256_file(path) != expected:
                    raise IntegrityError(
                        f"{label.replace('_', ' ').title()} changed after approval"
                    )
        return status
