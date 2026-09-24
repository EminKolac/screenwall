import { useEffect, useState } from "react";
import type { ChatMessage, ChatPreviewResponse, ProviderId, ProviderStatus } from "../../api/contract";
import { ApiError } from "../../api/client";
import { useChatPreview, useChatSend } from "../../api/queries";
import { errorMessage } from "../../copy/tr";
import { newId, type useConversation } from "./chatStore";

type ConversationApi = ReturnType<typeof useConversation>;

/** The server accepts at most this many earlier messages. */
export const HISTORY_LIMIT = 8;

/**
 * Everything one question will send, fixed at the moment it is asked. The same object feeds the
 * preview and the final request, so the consent dialog shows exactly what leaves the machine.
 */
interface Outgoing {
  question: string;
  provider: ProviderId;
  docIds: string[];
  history: ChatMessage[];
}

export interface PendingPreview {
  preview: ChatPreviewResponse;
  outgoing: Outgoing;
  mode: "consent" | "inspect";
}

const codeOf = (error: unknown) => (error instanceof ApiError ? error.code : "unknown_error");
const sameScope = (a: string[], b: string[]) => [...a].sort().join("\n") === [...b].sort().join("\n");

/**
 * Local providers answer directly; cloud providers need a previewed, consented payload first.
 * `selection` is the provider and document scope currently chosen in the panel: if either changes
 * while a preview is open, that preview (and any consent given for it) is dropped.
 */
export function useChatFlow(
  { conversation, append }: ConversationApi,
  selection: { provider: ProviderId; docIds: string[] },
) {
  const preview = useChatPreview();
  const send = useChatSend();
  const [pending, setPending] = useState<PendingPreview | null>(null);
  const [waitingSince, setWaitingSince] = useState<number | null>(null);
  const [error, setError] = useState<{ message: string; code: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const scopeKey = [...selection.docIds].sort().join("\n");

  useEffect(() => {
    if (waitingSince === null) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [waitingSince]);

  // A different destination or scope invalidates the previewed text.
  useEffect(() => {
    setPending((current) =>
      current && (current.outgoing.provider !== selection.provider || !sameScope(current.outgoing.docIds, selection.docIds))
        ? null
        : current,
    );
    // scopeKey stands in for the docIds array.
  }, [selection.provider, scopeKey]);

  const fail = (e: unknown) => {
    const code = codeOf(e);
    setError({ message: errorMessage(code), code });
  };

  const outgoingFor = (question: string, provider: ProviderId): Outgoing => ({
    question,
    provider,
    docIds: [...conversation.docIds],
    history: conversation.messages.slice(-HISTORY_LIMIT).map(({ role, content }) => ({ role, content })),
  });

  const deliver = async (outgoing: Outgoing, previewHash: string | null) => {
    append({ id: newId("m"), role: "user", content: outgoing.question, citations: [] });
    setWaitingSince(Date.now());
    try {
      const answer = await send.mutateAsync({
        doc_ids: outgoing.docIds,
        question: outgoing.question,
        provider: outgoing.provider,
        preview_hash: previewHash,
        history: outgoing.history,
      });
      append({
        id: newId("m"),
        role: "assistant",
        content: answer.answer,
        citations: answer.citations,
        provider: answer.provider,
        elapsedMs: answer.elapsed_ms,
      });
    } catch (e) {
      fail(e);
    } finally {
      setWaitingSince(null);
    }
  };

  const requestPreview = async (outgoing: Outgoing, mode: PendingPreview["mode"]) => {
    const result = await preview.mutateAsync({
      doc_ids: outgoing.docIds,
      question: outgoing.question,
      provider: outgoing.provider,
      history: outgoing.history,
    });
    setPending({ preview: result, outgoing, mode });
  };

  /** Returns true when the question left the composer (sent, or waiting in the consent dialog). */
  const ask = async (question: string, provider: ProviderStatus): Promise<boolean> => {
    setError(null);
    const outgoing = outgoingFor(question, provider.id);
    if (provider.local) {
      void deliver(outgoing, null);
      return true;
    }
    try {
      await requestPreview(outgoing, "consent");
    } catch (e) {
      fail(e);
    }
    return false;
  };

  const inspect = async (question: string, provider: ProviderStatus) => {
    setError(null);
    try {
      await requestPreview(outgoingFor(question, provider.id), "inspect");
    } catch (e) {
      fail(e);
    }
  };

  /** Sends the consented payload; false when there was nothing (still) valid to send. */
  const confirm = async (): Promise<boolean> => {
    if (!pending || pending.mode !== "consent") return false;
    const { preview: approved, outgoing } = pending;
    setPending(null);
    // Consent covers one previewed payload for one destination and scope, nothing else.
    if (outgoing.provider !== selection.provider || !sameScope(outgoing.docIds, selection.docIds)) return false;
    void deliver(outgoing, approved.preview_hash);
    return true;
  };

  return {
    ask,
    inspect,
    confirm,
    pending,
    closePreview: () => setPending(null),
    previewing: preview.isPending,
    waiting: waitingSince !== null,
    elapsed: waitingSince === null ? 0 : Math.max(0, Math.floor((now - waitingSince) / 1000)),
    error,
    clearError: () => setError(null),
  };
}
