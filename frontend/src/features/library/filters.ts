import type { DocStatus, DocumentSummary } from "../../api/contract";
import { isProcessing } from "../../api/queries";
import { tr } from "../../copy/tr";

export type FilterId = "all" | "review" | "approved" | "processing" | "failed";

export const FILTERS: FilterId[] = ["all", "review", "approved", "processing", "failed"];

export function matchesFilter(doc: DocumentSummary, filter: FilterId): boolean {
  switch (filter) {
    case "all":
      return true;
    case "review":
      return doc.status === "needs_review";
    case "approved":
      return doc.status === "approved";
    case "processing":
      return isProcessing(doc.status);
    case "failed":
      return doc.status === "failed";
  }
}

const fold = (value: string) => value.toLocaleLowerCase("tr").normalize("NFC");

export function filterDocs(docs: DocumentSummary[], query: string, filter: FilterId): DocumentSummary[] {
  const needle = fold(query.trim());
  return docs
    .filter((d) => matchesFilter(d, filter) && (!needle || fold(d.filename).includes(needle)))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function countByFilter(docs: DocumentSummary[]): Record<FilterId, number> {
  const counts = { all: 0, review: 0, approved: 0, processing: 0, failed: 0 };
  for (const doc of docs) for (const id of FILTERS) if (matchesFilter(doc, id)) counts[id] += 1;
  return counts;
}

const PROGRESS: Partial<Record<DocStatus, number>> = { queued: 12, extracting: 38, masking: 64, auditing: 86 };

export function progressFor(status: DocStatus): number {
  return PROGRESS[status] ?? 100;
}

/** The one-line explanation under a library row. */
export function reasonLine(doc: DocumentSummary): string | null {
  switch (doc.status) {
    case "needs_review":
      if (doc.counts.pending > 0) return tr.library.pending(doc.counts.pending);
      return doc.reasons[0]?.text ?? tr.library.readyToApprove;
    case "approved":
      return tr.library.approvedMeta(doc.counts.masked);
    case "failed":
      return doc.reasons[0]?.text ?? tr.library.failedMeta;
    case "rejected":
      return doc.reasons[0]?.text ?? null;
    default:
      return null;
  }
}

export const ACCEPTED_FILE = /\.(pdf|docx|xlsx)$/i;
export const ACCEPT_ATTR =
  ".pdf,.docx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
