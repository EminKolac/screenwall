import type { ChatSource, ProviderStatus } from "../../api/contract";
import { tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import type { UiMessage } from "./chatStore";
import { renderAnswer } from "./Citation";
import s from "./Chat.module.css";

interface MessageListProps {
  messages: UiMessage[];
  providers: ProviderStatus[];
  waiting: boolean;
  elapsed: number;
  onOpenSource: (source: ChatSource) => void;
}

const seconds = (ms: number) => (ms / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 });

export function MessageList({ messages, providers, waiting, elapsed, onOpenSource }: MessageListProps) {
  const label = (id: string | undefined) => providers.find((p) => p.id === id)?.label ?? id ?? "";
  return (
    <ol className={s.messages} aria-label={tr.chat.messagesLabel} aria-live="polite">
      {messages.map((message) => (
        <li key={message.id} className={cx(s.message, message.role === "user" ? s.user : s.assistant)}>
          <span className={s.who}>{message.role === "user" ? tr.chat.you : tr.chat.assistant}</span>
          <div className={s.bubble}>
            {message.role === "assistant" ? renderAnswer(message.content, message.citations, onOpenSource) : message.content}
          </div>
          {message.role === "assistant" && message.citations.length ? (
            <div className={s.sources}>
              <span className={s.sourcesTitle}>{tr.chat.sources}</span>
              <ul>
                {message.citations.map((source) => (
                  <li key={source.id}>
                    <button type="button" className={s.sourceRow} onClick={() => onOpenSource(source)}>
                      <span className={s.sourceId}>{source.id}</span>
                      <span className={s.sourceLabel}>{source.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {message.role === "assistant" && message.provider ? (
            <span className={s.meta}>{tr.chat.meta(label(message.provider), seconds(message.elapsedMs ?? 0))}</span>
          ) : null}
        </li>
      ))}
      {waiting ? (
        <li className={cx(s.message, s.assistant, s.waiting)}>
          <span className={s.dots} aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {tr.chat.waiting}
          <span className={s.elapsed} aria-hidden="true">
            {tr.chat.elapsed(elapsed)}
          </span>
        </li>
      ) : null}
    </ol>
  );
}
