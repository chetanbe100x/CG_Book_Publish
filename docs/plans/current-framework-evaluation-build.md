# Current Framework Evaluation Build

## Purpose

Generate a non-destructive, full-book evaluation DOCX from the current
framework and current draft manifest. This artifact is for manual review and
is not a certified print-ready final.

## Execution

- Preserve all inputs, retained references, templates, previews, and approved
  outputs.
- Use an isolated evaluation job and QA directory.
- Select source content pages 3 through 104 through the preview pipeline so
  the final-approval gate is not bypassed or weakened.
- Generate:
  `Books/Class 11/Maths/Preview/Class 11 Maths - Current Framework Evaluation Draft v1.docx`
- Do not resolve the existing 60 content-review items or tune layout before
  this evaluation build.

## Essential checks

- Microsoft Word opens and renders the DOCX without saving over it.
- Every rendered page is A4.
- The rendered page count is reported.
- The DOCX package is structurally valid.
- No unexpected blank overflow pages or square-box glyphs are detected.

## Handoff

The output remains clearly labelled as an evaluation draft. Feedback from the
manual review should be retained only when it materially improves the reusable
framework.
