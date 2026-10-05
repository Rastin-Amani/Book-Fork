# Document engine

Canonical reference. The engine turns untrusted EPUB/PDF uploads into one
format-independent model, segments it, and exports a translated artifact. The
detailed design (canonical model, placeholder protection, PDF reflow/OCR, safety
ceilings) lives in [`documents.md`](documents.md); the decision record is
[ADR 0003](decisions/0003-document-processing.md).

## Why a canonical model

EPUB and PDF are parsed into the same `CanonicalDocument` so translation,
segmentation, review and export never branch on the source format. Every job
exports a book PDF (`pymupdf` by default) and an EPUB, and target direction comes
from the language configuration read at runtime.

## Admin responsibilities

Format-independent behaviour is data: `document_max_*` ceilings are infrastructure
safety limits in the environment, while the user-facing size/page limits are
`upload.maximum_file_size` in system settings. There is no per-format business
logic to change in code.
