# Parser architecture (ContextHub)

ContextHub ingests NAS files through **scanner → parser → chunker → indexer**. Parsing uses a **routing layer** plus **format-specific adapters**. All adapters return the same internal contract: `ParseResult` (`markdown_text`, `blocks_json`, `metadata_json`, `page_count`, `parser_name`, `parser_version`), persisted in `document_parse_result`.

```
ParseRequest (bytes + ext + mime + filename)
        │
        ▼
   RoutingParser
        │
        ├── txt / md / markdown  → TextStubParser (native UTF-8)
        ├── pdf                  → PdfPypdfParser (pypdf)
        ├── docx                 → DocxPythonDocxParser (python-docx)
        ├── xlsx                 → XlsxOpenpyxlParser (openpyxl)
        ├── hwp / hwpx           → KordocCliParser (Node subprocess → kordoc)
        └── pptx                 → (reserved — explicit error)
        │
        ▼
   ParseResult → document_parse_result
```

Implementation entrypoint: `app/adapters/parsers/routing.py` (`RoutingParser`), invoked from `app/parser/service.py` (parse worker).

---

## Format strategy

| Format | Adapter | Engine | Notes |
|--------|---------|--------|-------|
| txt, md, markdown | `TextStubParser` | native UTF-8 | PoC text path |
| pdf | `PdfPypdfParser` | pypdf | No OCR in PoC |
| docx | `DocxPythonDocxParser` | python-docx | Headings from Word styles |
| xlsx | `XlsxOpenpyxlParser` | openpyxl | Sheets → markdown tables |
| hwp, hwpx | `KordocCliParser` | **kordoc** (external) | Subprocess CLI; no HWP logic in Python |
| pptx | — | 추후 | `ValueError` with clear message |

Existing **pdf/docx** adapters are unchanged in role; routing only adds **xlsx** and wires **hwp/hwpx** to kordoc.

---

## kordoc adapter (HWP/HWPX)

Python does **not** parse HWP directly. `KordocCliParser`:

1. Writes bytes to a temp file with the correct extension.
2. Runs a **Node CLI** (default: `node tools/kordoc-cli/parse.mjs`).
3. Reads **JSON from stdout** and maps to `ParseResult`.

### CLI contract (stdout JSON)

Success:

```json
{
  "ok": true,
  "markdown_text": "# …",
  "blocks_json": [],
  "metadata_json": {},
  "page_count": null,
  "parser_name": "kordoc",
  "parser_version": "kordoc-x.y.z"
}
```

Failure: non-zero exit code, or `{ "ok": false, "error": "…" }`.

### Configuration

| Env | Purpose |
|-----|---------|
| `KORDOC_CLI_COMMAND` | Override full argv prefix, e.g. `node C:/path/to/parse.mjs` |
| `KORDOC_ENGINE_CMD` | (Node bridge) When set, `parse.mjs` delegates to your real kordoc executable |
| `KORDOC_CLI_TIMEOUT_SECONDS` | Subprocess timeout (default 120) |

If `KORDOC_ENGINE_CMD` is unset, the bridge exits with a clear error until operations wires real kordoc.

See also: [parser-kordoc.md](parser-kordoc.md).

---

## Parse failures

On any parser exception or I/O error:

- `raw_document.parse_status = FAILED`
- `raw_document.parse_error_message` = truncated error text (max ~8k)
- No `document_parse_result` row

On success: `parse_error_message` is cleared.

Column added via dev migration: `python -m app.db.dev_migrations`.

---

## Operational reprocess flow

After adding or fixing parsers (e.g. xlsx, kordoc):

1. **List FAILED documents**  
   - Admin: `GET /api/v1/admin/documents/failed?stage=parse`  
   - SQL: `SELECT original_filename, inbox_path, parse_status, parse_error_message FROM raw_document WHERE parse_status = 'FAILED';`

2. **Fix root cause**  
   - xlsx: ensure `openpyxl` installed (`pip install -e .`)  
   - hwp/hwpx: configure `KORDOC_ENGINE_CMD` / real kordoc  
   - pptx: wait for adapter or exclude document

3. **Reprocess parse stage**  
   - `POST /api/v1/admin/documents/{raw_document_id}/reprocess`  
   - Body: `{"stage": "parse"}`  
   - Deletes chunks + `document_parse_result`, sets `parse_status=PENDING`, clears `parse_error_message`

4. **Run workers**  
   ```bash
   python -m app.workers
   ```

5. **Verify pipeline**  
   - `parse_status = DONE`  
   - `document_parse_result` exists  
   - `chunk_status` → chunker → `index_status` → indexer  
   - OpenSearch: filename/path fields contain expected tokens (see [search-quality.md](search-quality.md))

---

## Code map

| Path | Role |
|------|------|
| `app/adapters/parser_protocol.py` | `ParseRequest`, `ParseResult`, `ParserClient` |
| `app/adapters/parsers/routing.py` | `RoutingParser` |
| `app/adapters/parsers/pdf_pypdf.py` | PDF |
| `app/adapters/parsers/docx_python_docx.py` | DOCX |
| `app/adapters/parsers/xlsx_openpyxl.py` | XLSX |
| `app/adapters/parsers/kordoc_cli.py` | HWP/HWPX subprocess |
| `app/adapters/parsers/text_stub.py` | TXT/MD |
| `tools/kordoc-cli/parse.mjs` | Node CLI bridge |
| `app/parser/service.py` | Parse worker persistence |
