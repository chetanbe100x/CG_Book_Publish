# Accuracy-First Book Conversion Framework

Run all commands with the bundled workspace Python runtime. Every book is
described by a `job.json`, audited from its actual DOCX, previewed through seven
saved source-page boundaries, structurally validated, rendered, visually
reviewed, approved by hash, and only then converted in full.

```powershell
python automation\book_pipeline.py audit --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py preview --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py qa --job "Books\Class 12\Maths\job.json" --stage preview
python automation\book_pipeline.py approve-preview --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py full --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py qa --job "Books\Class 12\Maths\job.json" --stage final
python automation\book_pipeline.py status --job "Books\Class 12\Maths\job.json"
python automation\book_pipeline.py regression --job "Books\Class 12\Maths\job.json"
```

The Class 12 Maths `Final` file is registered from the already approved output,
so use `regression` to exercise full composition without overwriting it.

Record visual QA only after every rendered page has been inspected:

```powershell
python automation\record_visual_review.py --job "Books\Class 12\Maths\job.json" --stage preview --pages 9 --result pass --notes "Inspection notes"
```