# Template Execution Contract

## Reference

- Path: `D:\Experiments_Projects\CG_Book_Publish\Book_Template.docx`
- SHA-256: `FD6B76A7975CD3D72DEC61DD16511D3686A588E617B65090E936BCFBC9AA5261`
- Package parts: 21
- Section count: 1

## Page System

```json
[
  {
    "width_twips": "11906",
    "height_twips": "16838",
    "orientation": "portrait",
    "top_twips": "1440",
    "right_twips": "1440",
    "bottom_twips": "1260",
    "left_twips": "1440"
  }
]
```

The template's final section properties, header parts, footer parts,
relationships, decorative media, margins, and page-number field are
preserve-only.

## Editable Slot

- Package part: `word/document.xml`
- Slot: children of `w:body` before final `w:sectPr`
- Policy: replace from the audited source while preserving source text,
  typography, equations, numbering, tables, drawings, VML, and formatting.

## Package Preservation

- `Book_Template.docx` is immutable and must retain the SHA-256 above.
- Template headers, footers, relationships, and recurring media are preserve-only.
- `word/settings.xml` may only be changed to remove `w:updateFields`.
- Source dependencies are copied only when referenced by selected body content.

## Fidelity Gates

- Exact body token sequence and structural object counts.
- Valid XML and relationship targets.
- Template page geometry and recurring parts unchanged.
- Render every page to PNG and inspect before approval or delivery.
