import { useNavigate } from "react-router-dom";
import { tr } from "../../copy/tr";
import { docPath } from "../../app/paths";
import { ChatPanel } from "../chat/ChatPanel";
import { Badge } from "../../ui/Badge";
import { panelId, tabId, Tabs } from "../../ui/Tabs";
import { FindingsPanel } from "./FindingsPanel";
import { useReview } from "./reviewContext";
import s from "./ReviewWorkspace.module.css";

export type SideTab = "findings" | "chat";
const ID = "side";

/** Right-hand panel: "Bulgular" and "Sohbet". The tab lives in the URL (/d/:id and /d/:id/sohbet). */
export function SidePanel({ tab }: { tab: SideTab }) {
  const { doc, model, focusUnit } = useReview();
  const navigate = useNavigate();
  const pending = model.pendingOrder.length;

  return (
    <section className={s.side} aria-label={tr.findings.panelLabel}>
      <Tabs<SideTab>
        idBase={ID}
        label={tr.findings.panelLabel}
        value={tab}
        onChange={(next) => navigate(docPath(doc.id, next === "chat"), { replace: true })}
        items={[
          { id: "findings", label: tr.findings.tab, badge: pending ? <Badge tone="warn">{pending}</Badge> : null },
          { id: "chat", label: tr.chat.tab },
        ]}
      />
      <div role="tabpanel" id={panelId(ID, tab)} aria-labelledby={tabId(ID, tab)} className={s.sideBody}>
        {tab === "findings" ? <FindingsPanel /> : <ChatPanel doc={doc} onFocusUnit={focusUnit} />}
      </div>
    </section>
  );
}
