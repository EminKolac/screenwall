import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ChatSource, DocumentSummary, ProviderId } from "../../api/contract";
import { useProviders, useSettings } from "../../api/queries";
import { tr } from "../../copy/tr";
import { docPath } from "../../app/paths";
import { Button } from "../../ui/Button";
import { CopyText } from "../../ui/CopyText";
import { EmptyState } from "../../ui/EmptyState";
import { Icon } from "../../ui/Icon";
import { Skeleton } from "../../ui/Skeleton";
import { useConversation } from "./chatStore";
import { ConsentDialog } from "./ConsentDialog";
import { DocScope } from "./DocScope";
import { MessageList } from "./MessageList";
import { ProviderPicker, ProviderSummary } from "./ProviderPicker";
import { useChatFlow } from "./useChatFlow";
import s from "./Chat.module.css";

interface ChatPanelProps {
  doc: DocumentSummary;
  onFocusUnit: (unitId: string) => void;
}

function ChatReady({ doc, onFocusUnit }: ChatPanelProps) {
  const providers = useProviders();
  const settings = useSettings();
  const navigate = useNavigate();
  const chat = useConversation(doc.id);
  const [picked, setPicked] = useState<ProviderId | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const inputId = useId();

  const list = providers.data?.providers ?? [];
  const preferred = settings.data?.chat_default_provider ?? providers.data?.default ?? "ollama";
  const chosen =
    picked ??
    list.find((p) => p.id === preferred && p.available)?.id ??
    list.find((p) => p.available)?.id ??
    preferred;
  const provider = list.find((p) => p.id === chosen && p.available);
  const flow = useChatFlow(chat, { provider: chosen, docIds: chat.conversation.docIds });
  const busy = flow.waiting || flow.previewing;
  const canSend = Boolean(provider && question.trim() && !busy);

  const submit = async () => {
    if (!provider || !question.trim() || busy) return;
    const text = question.trim();
    const left = await flow.ask(text, provider);
    if (left) {
      setQuestion("");
      setPickerOpen(false);
    }
  };

  const confirm = async () => {
    const pendingQuestion = flow.pending?.outgoing.question;
    if (await flow.confirm()) {
      setQuestion((current) => (current.trim() === pendingQuestion ? "" : current));
      setPickerOpen(false);
    }
  };

  const openSource = (source: ChatSource) => {
    if (source.doc_id === doc.id) onFocusUnit(source.unit_id);
    else navigate(docPath(source.doc_id, true), { state: { focusUnit: source.unit_id } });
  };

  const loginHint = flow.error?.code === "cli_login_required" ? list.find((p) => p.id === chosen)?.login_command : null;
  // Once the conversation is under way the provider list folds into one line, leaving room to read.
  const summary = chat.conversation.messages.length > 0 && !pickerOpen ? provider : undefined;

  return (
    <div className={s.chat}>
      <div className={s.top}>
        {providers.isPending ? (
          <div className={s.providerSkeleton} aria-busy="true">
            <span className="sr-only">{tr.chat.providersLoading}</span>
            <Skeleton height={44} radius={6} />
            <Skeleton height={44} radius={6} />
          </div>
        ) : providers.isError ? (
          <p className={s.error} role="alert">
            {tr.chat.providersError}
          </p>
        ) : summary ? (
          <ProviderSummary provider={summary} onChange={() => setPickerOpen(true)} />
        ) : (
          <ProviderPicker providers={list} value={chosen} onChange={setPicked} />
        )}
        <DocScope current={doc} docIds={chat.conversation.docIds} onChange={(docIds) => chat.update({ docIds })} />
      </div>

      <div className={s.thread}>
        {chat.conversation.messages.length || flow.waiting ? (
          <MessageList
            messages={chat.conversation.messages}
            providers={list}
            waiting={flow.waiting}
            elapsed={flow.elapsed}
            onOpenSource={openSource}
          />
        ) : (
          <EmptyState icon="chat" title={tr.chat.emptyTitle} headingLevel="h2">
            {tr.chat.emptyBody}
          </EmptyState>
        )}
        {flow.error ? (
          <div className={s.error} role="alert">
            <Icon name="alert" size={15} />
            <span>{flow.error.message}</span>
            {loginHint ? <CopyText text={loginHint} /> : null}
          </div>
        ) : null}
      </div>

      <form
        className={s.composer}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          {tr.chat.inputLabel}
        </label>
        <textarea
          id={inputId}
          className={s.input}
          rows={2}
          value={question}
          placeholder={tr.chat.placeholder}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <div className={s.composerBar}>
          {provider?.local ? (
            <Button
              variant="link"
              size="sm"
              icon="eye"
              disabled={!question.trim() || busy}
              onClick={() => void flow.inspect(question.trim(), provider)}
            >
              {tr.chat.showPayload}
            </Button>
          ) : (
            <span />
          )}
          <Button type="submit" variant="primary" size="sm" icon="send" disabled={!canSend} loading={busy}>
            {tr.chat.send}
          </Button>
        </div>
      </form>

      <ConsentDialog
        preview={flow.pending?.preview ?? null}
        mode={flow.pending?.mode ?? "consent"}
        open={flow.pending !== null}
        onConfirm={() => void confirm()}
        onClose={flow.closePreview}
      />
    </div>
  );
}

/** "Sohbet" tab: only approved documents, only their masked text, with sources. */
export function ChatPanel({ doc, onFocusUnit }: ChatPanelProps) {
  if (!doc.can.chat) {
    return (
      <div className={s.locked}>
        <EmptyState icon="lock" title={tr.chat.lockedTitle} headingLevel="h2">
          {tr.chat.lockedBody}
        </EmptyState>
      </div>
    );
  }
  return <ChatReady doc={doc} onFocusUnit={onFocusUnit} />;
}
