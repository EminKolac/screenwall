// Fable v2 API contract — the single source of truth shared by backend and frontend.
// The backend (FastAPI) mirrors these shapes; the frontend imports them. Change both sides together.
//
// Conventions
// - All routes live under /api. JSON everywhere except page images (PNG) and download (PDF).
// - Every mutating request (POST/PUT/DELETE) sends the header X-CSRF-Token (see GET /api/session).
// - Errors: HTTP 4xx/5xx with body {"detail": ErrorCode}. The UI maps codes to Turkish sentences.
// - Offsets are Unicode code point indices (Python str indices). In JS, slice with Array.from(text).
// - No endpoint ever returns the placeholder→value mapping. Original text is returned only in
//   "mapping" mode and only to the review screen.

export type DocStatus =
  | "queued"
  | "extracting"
  | "masking"
  | "auditing"
  | "needs_review"
  | "approved"
  | "rejected"
  | "failed";

export type Mode = "mapping" | "destructive";
export type FileKind = "pdf" | "docx" | "xlsx";
export type Lang = "tr" | "en" | "mixed" | "unknown";

/** Why a document waits for a human (or failed). `text` is a ready-to-show Turkish sentence. */
export interface ReviewReason {
  code: string;
  text: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  kind: FileKind;
  mode: Mode;
  language: Lang;
  status: DocStatus;
  // Bumped on every (re-)anonymization. A review payload's spans, items and offsets belong to its
  // document.revision; decisions and approval echo it back as expected_revision.
  revision: number;
  created_at: string; // ISO 8601
  updated_at: string;
  pages: number | null; // PDF page count, else null
  counts: {
    masked: number; // spans currently masked
    pending: number; // open review items (suggestions + findings) that need a decision
  };
  reasons: ReviewReason[];
  can: {
    review: boolean; // GET /review is allowed (needs_review or approved)
    approve: boolean; // POST /approve would be accepted right now (no open items)
    download: boolean; // approved
    chat: boolean; // approved
    decide: boolean; // POST /decisions allowed (needs_review, mapping mode for unmask)
  };
}

export interface DocumentList {
  documents: DocumentSummary[];
}

// ---------------------------------------------------------------- review payload

export type UnitKind = "heading" | "paragraph" | "cell";

/** A text unit: a paragraph/heading block, or one table cell. Spans point at units. */
export interface ReviewUnit {
  id: string; // stable, e.g. "b12" or "b7:r3c2"
  block_id: string; // extraction block id
  kind: UnitKind;
  page: number | null; // 1-based page for PDFs
  location: string; // human label, e.g. "Sayfa 3" or "Sayfa1 · B4"
  table: { id: string; row: number; col: number } | null; // cells only
  original: string | null; // null in destructive mode
  masked: string;
}

export type SpanState = "masked" | "kept" | "added";

/** One masked value. `start/end` index `unit.original`; `masked_start/end` index `unit.masked`. */
export interface ReviewSpan {
  id: string;
  unit_id: string;
  start: number;
  end: number;
  masked_start: number;
  masked_end: number;
  family: string; // PERSON, ORG, LOCATION, TCKN, IBAN, PHONE, EMAIL, ...
  placeholder: string; // "<PERSON_1>"; for state "kept" the text stays unmasked
  evidence: string[]; // machine reason codes, e.g. "recognizer:TR_TCKN", "context:sayın"
  reason: string; // Turkish sentence built from evidence, e.g. "TCKN doğrulandı"
  state: SpanState;
}

export type ItemKind = "suggestion" | "finding";

/**
 * Something a human must decide. "suggestion": a plausible but unproven candidate the engine did
 * NOT mask. "finding": a residual the auditor flagged in the masked text. Both are visible text,
 * so both carry offsets into original and masked.
 */
export interface ReviewItem {
  id: string;
  kind: ItemKind;
  unit_id: string;
  start: number;
  end: number;
  masked_start: number;
  masked_end: number;
  family: string | null;
  reason: string; // Turkish sentence
  occurrences: number; // same text elsewhere in the document
  status: "open" | "masked" | "kept";
}

export interface PageInfo {
  index: number; // 1-based
  width: number; // PDF points
  height: number;
}

export interface ReviewPayload {
  document: DocumentSummary;
  units: ReviewUnit[];
  spans: ReviewSpan[];
  items: ReviewItem[];
  pages: PageInfo[]; // empty for non-PDF or destructive mode
}

/** GET /api/documents/{id}/pages/{n}/marks — rects are normalized 0..1 (x0, y0, x1, y1). */
export interface PageMarks {
  index: number;
  width: number;
  height: number;
  marks: {
    ref: string; // span id or item id
    kind: "masked" | "kept" | "added" | "suggestion" | "finding";
    rects: [number, number, number, number][];
  }[];
}

// ---------------------------------------------------------------- decisions

export type DecisionOp = "mask" | "unmask" | "keep";
export type DecisionScope = "occurrence" | "document" | "global";

export type DecisionTarget =
  | { span_id: string }
  | { item_id: string }
  | { unit_id: string; start: number; end: number; family: string }; // a new selection (original offsets)

export interface DecisionRequest {
  op: DecisionOp; // mask: hide it; unmask: a masked span was wrong; keep: an item is not personal data
  target: DecisionTarget;
  scope: DecisionScope; // occurrence | all occurrences in this document | global list (Settings)
  // The revision of the payload the decision was made on. Span ids are positional, so when given
  // and the document has moved on, the backend answers 409 stale_revision instead of guessing.
  expected_revision?: number;
}
// POST /api/documents/{id}/decisions -> ReviewPayload

export interface ApproveRequest {
  expected_revision?: number; // the revision the person reviewed; 409 stale_revision when it moved on
}
// POST /api/documents/{id}/approve -> DocumentSummary

export interface RejectRequest {
  reason?: string;
}

// ---------------------------------------------------------------- chat

export type ProviderId = "ollama" | "claude_cli" | "codex_cli";

export interface ProviderStatus {
  id: ProviderId;
  label: string; // "Yerel (Ollama)", "Claude", "Codex"
  local: boolean; // true only for ollama
  available: boolean; // ready to use right now
  installed: boolean | null; // CLI providers
  compatible: boolean | null; // CLI supports the required safety flags
  authenticated: boolean | null; // CLI logged in
  version: string | null;
  model: string | null;
  login_command: string | null; // shown as copyable text, never executed by the app
  problem: string | null; // ErrorCode when not available
}

export interface ProvidersResponse {
  default: ProviderId;
  providers: ProviderStatus[];
}

export interface ChatSource {
  id: string; // "S1"
  doc_id: string;
  unit_id: string;
  label: string; // "Sunum.pdf · Sayfa 3"
  excerpt: string; // masked text, max ~400 chars
}

export interface ChatPreviewRequest {
  doc_ids: string[];
  question: string;
  provider: ProviderId;
  // The exact history slice that POST /api/chat will send; it is part of sent_text and preview_hash.
  history: ChatMessage[];
}

export interface ChatPreviewResponse {
  provider: ProviderId;
  preview_hash: string;
  destination: string; // "Bu bilgisayar" | "Anthropic (Claude)" | "OpenAI (Codex)"
  sources: ChatSource[];
  sent_text: string; // exactly what will be sent (masked), for the consent dialog
  context_chars: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  doc_ids: string[];
  question: string;
  provider: ProviderId;
  preview_hash: string | null; // required for cloud providers
  history: ChatMessage[];
}

export interface ChatResponse {
  answer: string; // may contain [S1] markers
  citations: ChatSource[];
  provider: ProviderId;
  elapsed_ms: number;
}

// ---------------------------------------------------------------- settings, session, health

export interface AppSettings {
  default_mode: Mode;
  chat_default_provider: ProviderId;
  always_mask: string[];
  never_mask: string[];
}

export interface SessionResponse {
  csrf_token: string;
}

export interface HealthResponse {
  status: "ok";
  auditor: { provider: string; model: string; reachable: boolean };
  ocr: { available: boolean };
}

export type ErrorCode =
  | "document_not_found"
  | "document_busy"
  | "unsupported_file_type"
  | "file_too_large"
  | "invalid_file"
  | "extraction_failed"
  | "not_in_review"
  | "not_approved"
  | "no_content"
  | "unresolved_items"
  | "audit_not_clean"
  | "invalid_decision"
  | "stale_revision"
  | "original_not_stored"
  | "page_not_found"
  | "session_required"
  | "csrf_failed"
  | "chat_not_allowed"
  | "preview_required"
  | "preview_mismatch"
  | "provider_unavailable"
  | "ollama_unreachable"
  | "model_missing"
  | "cli_not_found"
  | "cli_upgrade_required"
  | "cli_login_required"
  | "cli_timeout"
  | "cli_output_limit"
  | "cli_failed"
  | "cli_unsafe_output"
  | "invalid_citations"
  | "internal_error";

// ---------------------------------------------------------------- routes (for reference)
//
// GET    /api/session                         -> SessionResponse (sets HttpOnly session cookie)
// GET    /api/health                          -> HealthResponse
// GET    /api/documents                       -> DocumentList
// POST   /api/documents   multipart file, mode? -> 202 DocumentSummary (status "queued")
// GET    /api/documents/{id}                  -> DocumentSummary
// DELETE /api/documents/{id}                  -> 204  (409 document_busy while extracting/masking/auditing;
//                                                  a queued document is deleted and its job skipped)
// GET    /api/documents/{id}/review           -> ReviewPayload
// GET    /api/documents/{id}/pages/{n}        -> image/png (mapping mode only)
// GET    /api/documents/{id}/pages/{n}/marks  -> PageMarks
// POST   /api/documents/{id}/decisions  DecisionRequest -> ReviewPayload  (409 stale_revision)
// POST   /api/documents/{id}/approve    ApproveRequest  -> DocumentSummary
//          409 not_in_review | stale_revision | no_content (nothing anonymized)
//          409 unresolved_items (open items; also when a fresh LLM audit just located a residual:
//              it is stored as a new finding and the revision is bumped)
//          409 audit_not_clean (a fresh LLM audit found something: look again, approve again)
//          503 ollama_unreachable (the LLM auditor is unavailable; nothing was approved)
// POST   /api/documents/{id}/reject           -> DocumentSummary
// GET    /api/documents/{id}/masked           -> text/plain (needs_review or approved)
// GET    /api/documents/{id}/download         -> application/pdf (approved only)
// GET    /api/chat/providers                  -> ProvidersResponse
// POST   /api/chat/preview                    -> ChatPreviewResponse
// POST   /api/chat                            -> ChatResponse
// GET    /api/settings                        -> AppSettings
// PUT    /api/settings                        -> AppSettings
