export default function StatusBadge({ status, label }: { status: string; label: string }) {
  const tone =
    status === "approved" ? "ok" : status === "needs_human_review" ? "warn" : "info";
  return <span className={"badge " + tone}>{label}</span>;
}
