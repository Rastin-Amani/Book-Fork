# Document engine

Format-agnostic document processing. The translation engine depends only on the
**canonical model**, never on EPUB or PDF internals.

```
Input file → Document adapter → Canonical document → Structural normalization
→ Segmentation → (Translation) → Canonical translated document → Output adapter → Translated file
```

## Canonical model (`app/documents/model.py`)

- `CanonicalDocument` → `metadata`, `sections[]`, `assets[]`, `warnings[]`,
  `canonical_model_version`.
- `Section` → `id`, `title`, `source_order`, `source_ref`, `blocks[]`, `asset_ids[]`.
- `TextBlock` → `id`, `type` (heading, paragraph, quote, list, list_item,
  caption, table, code, image, separator, unknown), `source_text`,
  `translated_text`, `source_order`, `parent_id`, `level`, `source_ref`,
  `formatting`, `attributes`, `links`, `style`, `placeholders`.
- `Asset` → `id`, `filename`, `media_type`, `storage_key`.

**Identity.** IDs are deterministic (`section_003`, `block_0041`) and stable for a
fixed source, and every block also carries a `source_ref` anchor (element id or
archive member + ordinal). Array position is not the only identity.

**Translatable text carries inline markup.** For rich formats `source_text` is the
block's inner markup so inline formatting survives translation; the
`PlaceholderProtector` strips markup into opaque tokens before text reaches a
provider. `attributes["plain_text"]` holds the text-only content for language
detection and sentence splitting.

**Serialization.** `app/documents/serialization.py` writes a versioned JSON tree
to object storage at `documents/{id}/canonical/v{n}.json` — never into a
PocketBase record.

## Adapters (`app/documents/adapters/`)

- `DocumentParser` / `DocumentExporter` protocols, selected by `DocumentType` via
  `AdapterRegistry` (`default_registry()` wires EPUB and PDF).

### EPUB (`app/documents/epub/`)

- Safe ZIP inspection (traversal, symlink, entry-count, size and compression-ratio
  limits), plus `mimetype` validation.
- Preserves metadata, spine/chapter order, headings, paragraphs, lists,
  quotes, captions, tables, images, links and inline markup.
- Export rebuilds a valid EPUB 3 (metadata, manifest, spine, nav, stylesheets,
  images, order). Only translatable text is replaced; `lang`/`dir` come from the
  target language configuration, so RTL targets are correct. Anchors/IDs are kept.

### PDF (`app/documents/pdf/`)

- PyMuPDF extraction, rebuilt from *lines* rather than MuPDF's page blocks:
  spans separated by a horizontal gap get a space, glued runs like
  `overratedPlanning`/`FIRSTThe` are split, paragraphs start where a line is
  indented, and list markers (bullets and numbers, Latin or Arabic-Indic) are
  recognized, stripped from the translatable text and remembered. A line is a
  heading when it is **bold** or clearly larger than the body size; when the
  document has font-size titles those become level-1 chapters and bold-only
  lines become level-2 subheads, so every bold line no longer starts a new page.
  This recovers chapter structure and a usable table of contents from converted
  ebooks whose text layer is a single block per page.
- The first page is rendered as the **document cover**.
- Page number, bounding box and font size are preserved; list markers detected;
  images captured as assets; printed contents/index pages are not treated as
  chapter headings.
- Pages with no extractable text are flagged `ocr_required` (not forced through
  OCR).

## OCR (`app/documents/ocr/`)

`OcrProvider` protocol with a `NullOcrProvider` default. The pipeline reports
`ocr_required` / `ocr_unavailable` / `ocr_completed` cleanly and never mandates a
provider. Concrete providers (tesseract, paddleocr, cloud) plug in behind the
interface.

## Segmentation (`app/documents/segmentation/`)

Structure-aware, not a character chop. Strategies: `paragraph`, `sentence`,
`structure_aware` (default). Sentence splitting uses `pysbd` across languages
(Persian, Arabic, German, Japanese, Chinese, …) and **falls back to
paragraph-level** when the language is unsupported or the block carries markup.
Segment IDs are stable: `{block_id}#s{index}`.

## Placeholder protection (`app/documents/placeholders.py`)

Replaces URLs, emails, HTML tags, markdown links/images, template syntax and
inline code with opaque tokens before translation, and restores them afterwards.
Never relies on an LLM instruction alone to preserve a URL.

## Book output (`app/documents/book/`)

Every completed job produces a set of downloadable books (`DOCUMENT_OUTPUT_FORMATS`,
default `epub,pdf`), independent of the source format:

- **PDF** (`pymupdf`, default): a print-ready book via PyMuPDF's Story engine —
  the document's **own cover** when one exists (EPUB cover image, or the first
  PDF page), a contents page with printed page numbers and clickable rows, running
  heads, page numbers, a PDF outline and a new page at each chapter. Headings are
  kept with the text they introduce even though Story ignores
  `page-break-after: avoid`; list items get a real bullet or number on the correct
  side for RTL; cover, running heads and contents are direction-aware.
  Pure Python (no system libraries) and RTL-aware. `html` emits the reflow
  preview; `weasyprint` is the optional extra backend. `DOCUMENT_BOOK_PAGE_SIZE`
  picks the trim size.
- **EPUB** (`app/documents/epub/`): a valid EPUB 3 rebuild with the document's own
  cover (or a generated one), book CSS, embedded fonts, both an EPUB 3 `nav` and
  a legacy `toc.ncx`, cover/nav landmarks, and `page-progression-direction="rtl"`
  for RTL targets. Cover and navigation documents are excluded from translation
  on re-import. PDF sources are grouped into chapters at their recovered level-1
  headings, so they get a real menu too.

`render_backend` is configuration-driven (`DOCUMENT_RENDER_BACKEND`).
The reflowed HTML sets `lang`/`dir` from the target language.

## Book typography (fonts)

Bundled, SIL OFL fonts are embedded in both PDF and EPUB so output is
self-contained and prints correctly, even with no system fonts installed:

- **Vazirmatn** for Persian/Arabic-script targets (`fa`, `ar`, `ur`, …).
- **Crimson Text** for Latin, Greek and Cyrillic targets.

Other scripts (Hebrew, Devanagari, CJK, …) map to Google "Noto Serif" families.
Install `Family-Regular.ttf` / `Family-Bold.ttf` into `DOCUMENT_FONT_DIR` and the
resolver uses them; without them the bundled default is used as a fallback.

## Safety (`app/documents/safety.py`)

Content/extension sniffing, SHA-256 checksums, archive validation
(traversal/symlink/entry/size/ratio), hard per-member size ceilings, managed
temporary directories that always clean up. All limits are configuration.

## Engine (`app/documents/service.py`)

`DocumentEngine` wires adapters, segmentation, protection and storage together
(and holds the optional OCR provider). It is LLM-agnostic: it prepares protected
segments and can restore translations, but knows nothing about providers.
