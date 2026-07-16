# Repository Guidelines

## Project Structure & Module Organization

The Python entry point is `automation/book_pipeline.py`. Shared OOXML logic lives in `automation/framework/core/`; feature handlers are in `capabilities/`, rendering and validation in `qa/`, and subject defaults in `profiles/`. Keep book-specific exceptions in `adapters/` instead of adding subject assumptions to core code. Unit tests are under `automation/tests/unit/`, while approved end-to-end cases belong in `automation/tests/regression/`.

Each book uses `Books/<Class>/<Subject>/` with a `job.json` plus `Input/`, `Preview/`, `Final/`, and `QA/`. `Book_Template.docx` is the canonical template. Root source and approved-output DOCX files are protected regression artifacts.

## Build, Test, and Development Commands

Run commands from the repository root with Python 3.12 or the bundled workspace runtime:

```powershell
python -m compileall -q automation
python -m unittest discover -s automation\tests\unit -t automation -v
python automation\book_pipeline.py audit --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py preview --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py qa --job "Books\Class 12\Maths\job.json" --stage preview
python automation\book_pipeline.py regression --job "Books\Class 12\Maths\job.json"
```

Audit before composition. Complete conversion requires a QA-passed, explicitly approved preview hash.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `pathlib.Path`, and `from __future__ import annotations`. Name modules and functions in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. Keep OOXML namespace handling centralized in `core/package.py`. Prefer small capability modules and fail closed on unsupported document objects. No formatter is configured; follow standard PEP 8 and keep imports grouped.

## Testing Guidelines

Tests use `unittest`; name files `test_*.py` and methods `test_*`. Add unit coverage for boundary, relationship, hash, and failure behavior. Any shared composition change must pass every case in `automation/tests/regression/`. Render previews and finals, inspect every page, and record visual QA only after inspection.

## Commit & Pull Request Guidelines

No Git history is currently available. Use imperative Conventional Commit messages such as `fix: preserve numbering relationships`. Pull requests should describe affected pipeline stages, list commands run, identify changed protected hashes, and include preview/final page counts plus visual-QA results. Never commit substituted fonts, overwritten inputs, or unreviewed generated finals.

## Security & Integrity

Never overwrite canonical inputs, templates, previews, or approved outputs. Preserve automatic field updating as disabled, do not open delivered DOCX files through LibreOffice for saving, and stop when required fonts or relationships are missing.
