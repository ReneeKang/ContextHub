# Sample documents (PoC)

| File | Purpose |
|------|---------|
| `sample.pdf` | Two-page PDF with extractable text (`PDF_SAMPLE_KEYWORD`). |
| `sample.docx` | DOCX with headings + `DOCX_SAMPLE_KEYWORD`. |

**OCR is not used**; scanned PDFs may yield empty or placeholder page sections.

## Local pipeline test order

1. Copy (or hard-link) files into your NAS inbox, e.g.  
   `local_nas/chatbot_docs/public/sample.pdf` and `local_nas/chatbot_docs/public/sample.docx`  
   (same `public/` tree as other permission samples).
2. Run **`python -m app.workers`** twice so the scanner stabilizes mtime/size and registers `raw_document` rows.
3. Run workers again (or more cycles) until parser → chunker → indexer logs show the new documents as **DONE**.
4. **`GET /api/v1/admin/documents`** — confirm `file_ext` is `pdf` / `docx` and parse/chunk/index statuses.
5. **`POST /api/v1/chat/query`** — e.g. question `PDF_SAMPLE_KEYWORD` or `DOCX_SAMPLE_KEYWORD` with appropriate stub principal / departments.

Regenerating binaries (optional): use any PDF/DOCX generator you prefer; the repo commits small fixtures for repeatable CI and onboarding.
