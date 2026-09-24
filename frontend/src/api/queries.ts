// TanStack Query hooks. Server state lives here; components never call fetch directly.
import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AppSettings,
  DecisionRequest,
  DocStatus,
  DocumentSummary,
  Mode,
  ReviewPayload,
} from "./contract";
import { api, ApiError } from "./client";

export const keys = {
  documents: ["documents"] as const,
  review: (id: string) => ["review", id] as const,
  pageMarks: (id: string, page: number) => ["pageMarks", id, page] as const,
  providers: ["providers"] as const,
  settings: ["settings"] as const,
  health: ["health"] as const,
};

const PROCESSING: ReadonlySet<DocStatus> = new Set(["queued", "extracting", "masking", "auditing"]);

export function isProcessing(status: DocStatus): boolean {
  return PROCESSING.has(status);
}

export const POLL_MS = 1500;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return count < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

/** The library. Polls every 1.5 s only while at least one document is still being processed. */
export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: ({ signal }) => api.documents(signal).then((r) => r.documents),
    refetchInterval: (query) =>
      query.state.data?.some((d) => isProcessing(d.status)) ? POLL_MS : false,
  });
}

export function useReviewPayload(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.review(id),
    queryFn: ({ signal }) => api.review(id, signal),
    enabled,
    staleTime: 30_000,
  });
}

export function usePageMarks(id: string, page: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.pageMarks(id, page),
    queryFn: ({ signal }) => api.pageMarks(id, page, signal),
    enabled,
    staleTime: 30_000,
  });
}

function usePatchSummary() {
  const qc = useQueryClient();
  return (summary: DocumentSummary) => {
    qc.setQueryData<DocumentSummary[]>(keys.documents, (prev) =>
      prev ? prev.map((d) => (d.id === summary.id ? summary : d)) : prev,
    );
  };
}

/**
 * 409s meaning the review on screen is out of date: the hooks reload it before rethrowing.
 * unresolved_items too: approval's fresh LLM audit may just have stored new open findings.
 */
export type ReviewReload = "stale_revision" | "audit_not_clean" | "unresolved_items";
const RELOADS: ReadonlySet<string> = new Set<ReviewReload>(["stale_revision", "audit_not_clean", "unresolved_items"]);
const reloads = (code: string): code is ReviewReload => RELOADS.has(code);

export function reviewReload(error: unknown): ReviewReload | null {
  return error instanceof ApiError && reloads(error.code) ? error.code : null;
}

/** Refetches the review, its page marks and the library; resolves once the active ones are back. */
function useReloadReview(id: string) {
  const qc = useQueryClient();
  return async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.review(id) }),
      qc.invalidateQueries({ queryKey: ["pageMarks", id] }),
      qc.invalidateQueries({ queryKey: keys.documents }),
    ]);
  };
}

/** A decision pinned to the payload revision it was made on (span ids are positional). */
export type RevisedDecision = DecisionRequest & { expected_revision: number };

export function useDecide(id: string) {
  const qc = useQueryClient();
  const patch = usePatchSummary();
  const reload = useReloadReview(id);
  return useMutation({
    mutationFn: (body: RevisedDecision) => api.decide(id, body),
    onSuccess: (payload: ReviewPayload) => {
      qc.setQueryData(keys.review(id), payload);
      patch(payload.document);
      void qc.invalidateQueries({ queryKey: ["pageMarks", id] });
    },
    // Returned, so mutateAsync rejects only after the current review is on screen.
    onError: (error) => (reviewReload(error) ? reload() : undefined),
  });
}

export function useApprove(id: string) {
  const qc = useQueryClient();
  const patch = usePatchSummary();
  const reload = useReloadReview(id);
  return useMutation({
    mutationFn: (expectedRevision: number) => api.approve(id, { expected_revision: expectedRevision }),
    onSuccess: (summary) => {
      patch(summary);
      void qc.invalidateQueries({ queryKey: keys.review(id) });
      void qc.invalidateQueries({ queryKey: keys.documents });
    },
    onError: (error) => (reviewReload(error) ? reload() : undefined),
  });
}

export function useReject(id: string) {
  const qc = useQueryClient();
  const patch = usePatchSummary();
  return useMutation({
    mutationFn: (reason: string) => api.reject(id, reason ? { reason } : {}),
    onSuccess: (summary) => {
      patch(summary);
      void qc.invalidateQueries({ queryKey: keys.documents });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.remove(id),
    onSuccess: (_void, id) => {
      qc.setQueryData<DocumentSummary[]>(keys.documents, (prev) => prev?.filter((d) => d.id !== id));
      qc.removeQueries({ queryKey: keys.review(id) });
      void qc.invalidateQueries({ queryKey: keys.documents });
    },
    onError: (error) => {
      // The list still thought the document was settled: fetch its real (processing) status.
      if (error instanceof ApiError && error.code === "document_busy") {
        void qc.invalidateQueries({ queryKey: keys.documents });
      }
    },
  });
}

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, mode }: { file: File; mode: Mode }) => api.upload(file, mode),
    onSuccess: (summary) => {
      qc.setQueryData<DocumentSummary[]>(keys.documents, (prev) =>
        prev ? [summary, ...prev.filter((d) => d.id !== summary.id)] : [summary],
      );
      void qc.invalidateQueries({ queryKey: keys.documents });
    },
  });
}

export function useProviders(enabled = true) {
  return useQuery({
    queryKey: keys.providers,
    queryFn: ({ signal }) => api.providers(signal),
    enabled,
    staleTime: 60_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: ({ signal }) => api.settings(signal),
    staleTime: 60_000,
  });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AppSettings) => api.saveSettings(body),
    onSuccess: (settings) => {
      qc.setQueryData(keys.settings, settings);
      void qc.invalidateQueries({ queryKey: keys.providers });
    },
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
    retry: false,
  });
}

export function useChatPreview() {
  return useMutation({ mutationFn: api.chatPreview });
}

export function useChatSend() {
  return useMutation({ mutationFn: api.chat });
}
