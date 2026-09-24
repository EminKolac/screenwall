import { Fragment, type ReactNode } from "react";
import type { ChatSource } from "../../api/contract";
import { tr } from "../../copy/tr";
import s from "./Chat.module.css";

interface CitationProps {
  id: string;
  source: ChatSource | undefined;
  onOpen: (source: ChatSource) => void;
}

/** An [S1] marker as a chip that jumps to the cited unit in the masked pane. */
export function Citation({ id, source, onOpen }: CitationProps) {
  if (!source) return <span className={s.citeMissing}>[{id}]</span>;
  return (
    <button
      type="button"
      className={s.cite}
      title={source.label}
      aria-label={tr.chat.citation(source.id, source.label)}
      onClick={() => onOpen(source)}
    >
      {source.id}
    </button>
  );
}

const MARKER = /(\[S\d+\])/g;

/** Answer text with its [S1] markers turned into citation chips. */
export function renderAnswer(text: string, citations: ChatSource[], onOpen: (source: ChatSource) => void): ReactNode[] {
  return text.split(MARKER).map((part, index) => {
    const match = /^\[(S\d+)\]$/.exec(part);
    if (!match) return <Fragment key={index}>{part}</Fragment>;
    return <Citation key={index} id={match[1]} source={citations.find((c) => c.id === match[1])} onOpen={onOpen} />;
  });
}
