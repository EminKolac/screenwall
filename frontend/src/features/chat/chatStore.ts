// In-memory conversations for this app session. Nothing is persisted: the chat stays on this page.
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { ChatSource, ProviderId } from "../../api/contract";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatSource[];
  provider?: ProviderId;
  elapsedMs?: number;
}

export interface Conversation {
  id: string;
  docIds: string[];
  messages: UiMessage[];
  updatedAt: number;
}

let conversations: Conversation[] = [];
const listeners = new Set<() => void>();
let seq = 0;

const store = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  snapshot: () => conversations,
  save(next: Conversation) {
    conversations = [...conversations.filter((c) => c.id !== next.id), { ...next, updatedAt: Date.now() + seq++ / 1000 }];
    listeners.forEach((l) => l());
  },
};

/** Test isolation only: forget this session's conversations. */
export function resetConversations(): void {
  conversations = [];
  listeners.forEach((l) => l());
}

export const newId = (prefix: string) => `${prefix}${Date.now().toString(36)}${(seq++).toString(36)}`;

/** The latest conversation that includes `docId`, or a fresh draft scoped to it. */
export function useConversation(docId: string) {
  const all = useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
  const conversation = useMemo<Conversation>(() => {
    const latest = [...all].sort((a, b) => b.updatedAt - a.updatedAt).find((c) => c.docIds.includes(docId));
    return latest ?? { id: `draft-${docId}`, docIds: [docId], messages: [], updatedAt: 0 };
  }, [all, docId]);

  const update = useCallback(
    (patch: Partial<Conversation>) => {
      const current = store.snapshot().find((c) => c.id === conversation.id) ?? conversation;
      store.save({ ...current, ...patch });
    },
    [conversation],
  );

  const append = useCallback(
    (message: UiMessage) => {
      const current = store.snapshot().find((c) => c.id === conversation.id) ?? conversation;
      store.save({ ...current, messages: [...current.messages, message] });
    },
    [conversation],
  );

  const restart = useCallback(() => {
    store.save({ id: newId("c"), docIds: [docId], messages: [], updatedAt: 0 });
  }, [docId]);

  return { conversation, update, append, restart };
}
