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
    preview_source_pages: int = 7
    content_policy: str = "layout_only"
    typography_policy: str = "preserve_source"
    subject_profile: str = "science"
    adapter: str | None = None
    required_fonts: tuple[str, ...] = field(default_factory=tuple)

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

        job = JobConfig(
            manifest_path=manifest,
            job_id=str(data["job_id"]),
            school_class=str(data["class"]),
            subject=str(data["subject"]),
            source=resolve("source"),
            template=resolve("template"),
            preview_output=resolve("preview_output"),
            final_output=resolve("final_output"),
            approved_reference=resolve("approved_reference", optional=True),
            qa_dir=resolve("qa_dir"),
            preview_source_pages=int(data.get("preview_source_pages", 7)),
            content_policy=str(data.get("content_policy", "layout_only")),
            typography_policy=str(data.get("typography_policy", "preserve_source")),
            subject_profile=str(data.get("subject_profile", "science")),
            adapter=data.get("adapter"),
            required_fonts=tuple(str(v) for v in data.get("required_fonts", [])),
        )
        job.validate()
        return job

    def validate(self) -> None:
        if not self.source.is_file():
            raise FrameworkError(f"Source DOCX not found: {self.source}")
        if not self.template.is_file():
            raise FrameworkError(f"Template DOCX not found: {self.template}")
        if self.approved_reference is not None and not self.approved_reference.is_file():
            raise FrameworkError(f"Approved reference not found: {self.approved_reference}")
        if self.preview_source_pages < 1:
            raise FrameworkError("preview_source_pages must be positive")
        if self.content_policy != "layout_only":
            raise FrameworkError("Only layout_only content policy is implemented")
        if self.typography_policy != "preserve_source":
            raise FrameworkError("Only preserve_source typography policy is implemented")
        protected = {self.source, self.template}
        if self.preview_output in protected or self.final_output in protected:
            raise IntegrityError("Output path collides with a protected input")

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
        for label, path in (("source", self.job.source), ("template", self.job.template)):
            expected = status.get(f"approved_{label}_sha256")
            if expected and sha256_file(path) != expected:
                raise IntegrityError(f"{label.title()} changed after preview approval")
        return status
