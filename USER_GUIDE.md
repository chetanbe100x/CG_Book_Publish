# Book Conversion Framework - User Guide

## 1. What This Framework Does

The framework places the contents of an input Word book into the approved page template while preserving text, fonts, sizes, equations, numbering, tables, images, answer lines, and direct formatting.

Every new book follows the same controlled process:

```text
Input -> Audit -> Seven-source-page preview -> QA -> User approval
      -> Complete conversion -> Final QA -> Final book
```

The original input, template, approved preview, and final output are never overwritten.

## 2. Before You Begin

Confirm that:

- The complete book is available as one `.docx` file.
- `D:\Experiments_Projects\CG_Book_Publish\Book_Template.docx` exists.
- Microsoft Word and LibreOffice are installed.
- Fonts used by the input book are installed on the computer.
- The input DOCX is closed in Word before processing.

LibreOffice is used only to generate QA images. It does not save the delivered DOCX.

## 3. Where to Place a New Input

Create a folder using the book's class and subject:

```text
D:\Experiments_Projects\CG_Book_Publish\
+-- Book_Template.docx
\-- Books\
    \-- Class 11\
        \-- Maths\
            \-- Input\
                \-- 11 CLASS MATHS.docx
```

Only place the source document in `Input`. The process creates these automatically:

```text
Books\Class 11\Maths\
+-- job.json
+-- Input\
+-- Preview\
+-- Final\
\-- QA\
```

Do not place or edit files manually in `Preview`, `Final`, or `QA`.

## 4. Start a New Book

Open Codex in the project folder and use this prompt, replacing the example values:

```text
Register and process a new book using the Accuracy-First Book Conversion Framework.

Class: 11
Subject: Maths
Input:
D:\Experiments_Projects\CG_Book_Publish\Books\Class 11\Maths\Input\11 CLASS MATHS.docx

Template:
D:\Experiments_Projects\CG_Book_Publish\Book_Template.docx

Create the required folders and job.json. Audit the actual input and select
capabilities from its detected content. Check required fonts and stop if any
are missing. Generate only the first seven source-page preview. Preserve all
educational content and formatting objects. Run structural validation, render
and visually inspect every preview page, and produce the QA report. Do not run
the complete conversion. Do not modify or overwrite the input or template.
Stop and wait for my explicit approval.
```

The preview may contain more than seven output pages because the template has different margins and usable page space. "Seven pages" always means seven saved pages from the source document.

## 5. Review the Preview

Open the file in:

```text
Books\<Class>\<Subject>\Preview\
```

Check:

- No text, equations, tables, or images are missing.
- Fonts, sizes, bold, italics, and alignment match the source.
- Content remains inside the decorative frame.
- Page numbers start at 1 and continue correctly.
- No content is clipped, overlapping, or unexpectedly substituted.

If Word asks whether to update fields that may refer to other files, choose **No**. Automatic field updating is intentionally disabled.

If corrections are needed, describe the page number and exact issue. Do not edit the preview manually because any change invalidates its approval hash.

## 6. Approve and Generate the Full Book

After the preview is satisfactory, use:

```text
I approve this preview:
<full path to the preview DOCX>

Record its approval hash and perform the complete conversion. Run structural
validation and all registered regression cases. Render and inspect every final
page. Place the completed DOCX in the Final folder. Do not overwrite the input,
template, or approved preview.
```

Complete conversion is blocked if the preview was not approved or if the input, template, or preview changed after approval.

## 7. Find the Results

```text
Preview DOCX: Books\<Class>\<Subject>\Preview\
Final DOCX:   Books\<Class>\<Subject>\Final\
QA report:    Books\<Class>\<Subject>\QA\QA Report.txt
Job status:   Books\<Class>\<Subject>\QA\status.json
Page images:  Books\<Class>\<Subject>\QA\<Stage> Render\
```

The final file is ready only when structural validation, visual inspection, and regression checks all pass.

## 8. Processing Another Subject or Class

Use a separate folder and audit for every book, even if the subject was previously approved. For example:

```text
Books\Class 12\Science\Input\12 CLASS SCIENCE.docx
Books\Class 11\Maths\Input\11 CLASS MATHS.docx
Books\Class 10\Hindi\Input\10 CLASS HINDI.docx
```

Previously approved subjects provide regression protection, but they do not determine the new book's fonts, sizes, or checks. These are always derived from the actual input.

## 9. Common Problems

### Missing font

The process stops instead of substituting a font. Install the exact font reported by the audit, close Word, and rerun the preview process.

### Input has no saved page boundaries

Open the input in Microsoft Word, allow it to paginate completely, save it as DOCX, close Word, and retry.

### LibreOffice render failure

Confirm LibreOffice opens normally and that the DOCX is not open elsewhere. Rendering problems affect QA; they do not authorize skipping visual inspection.

### Preview changed after approval

Run preview QA again and approve the new hash. Never bypass the approval check.

## 10. Important Rules

- Never replace `Book_Template.docx` without creating and approving a new template baseline.
- Never rename, edit, or delete input files during an active job.
- Never approve a preview without opening and reviewing it.
- Never deliver a final DOCX without a passing QA report.
- Keep each class and subject in its own folder.
