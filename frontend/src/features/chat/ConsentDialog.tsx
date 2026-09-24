import { useEffect, useId, useState } from "react";
import type { ChatPreviewResponse } from "../../api/contract";
import { tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Icon } from "../../ui/Icon";
import s from "./Chat.module.css";

interface ConsentDialogProps {
  preview: ChatPreviewResponse | null;
  /** "consent": a cloud send that needs an explicit yes. "inspect": read-only look at a local payload. */
  mode: "consent" | "inspect";
  open: boolean;
  sending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

const count = new Intl.NumberFormat("tr-TR");

export function ConsentDialog({ preview, mode, open, sending = false, onConfirm, onClose }: ConsentDialogProps) {
  const [agreed, setAgreed] = useState(false);
  const agreeId = useId();

  useEffect(() => {
    setAgreed(false);
  }, [open, preview?.preview_hash]);

  if (!preview) return null;
  const consent = mode === "consent";
  // The flow opens "consent" for every non-local provider, including an explicitly allowed remote
  // Ollama, so the mode (not the provider's name) says whether the text leaves this machine.
  const local = !consent;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={consent ? tr.chat.consent.title : tr.chat.consent.inspectTitle}
      footer={
        consent ? (
          <>
            <Button variant="quiet" onClick={onClose}>
              {tr.common.cancel}
            </Button>
            <Button variant="primary" icon="send" disabled={!agreed} loading={sending} onClick={onConfirm}>
              {tr.chat.consent.send}
            </Button>
          </>
        ) : (
          <Button onClick={onClose}>{tr.common.close}</Button>
        )
      }
    >
      <div className={s.destination}>
        <span className={s.destinationIcon} aria-hidden="true">
          <Icon name={local ? "computer" : "cloud"} size={18} />
        </span>
        <span className={s.destinationText}>
          <span className={s.destinationLabel}>{tr.chat.consent.destination}</span>
          <strong>{preview.destination}</strong>
        </span>
      </div>
      <p className={s.consentBody}>{local ? tr.chat.consent.localBody : tr.chat.consent.cloudBody(preview.destination)}</p>

      <section className={s.consentSection}>
        <h3 className={s.consentHeading}>
          {tr.chat.consent.sources}
          <Badge tone="count">{preview.sources.length}</Badge>
        </h3>
        <ul className={s.consentSources}>
          {preview.sources.map((source) => (
            <li key={source.id}>
              <span className={s.sourceId}>{source.id}</span>
              <span className={s.sourceLabel}>{source.label}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className={s.consentSection}>
        <h3 className={s.consentHeading}>
          {tr.chat.consent.payload}
          <span className={s.chars}>{tr.chat.consent.chars(count.format(preview.context_chars))}</span>
        </h3>
        <pre className={s.payload} tabIndex={0} role="region" aria-label={tr.chat.consent.payload}>
          {preview.sent_text}
        </pre>
      </section>

      {consent ? (
        <div className={s.agree}>
          <input id={agreeId} type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
          <label htmlFor={agreeId}>{tr.chat.consent.checkbox(preview.destination)}</label>
        </div>
      ) : null}
    </Dialog>
  );
}
