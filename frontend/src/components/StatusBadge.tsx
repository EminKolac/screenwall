/* Rozet yalnız DİKKAT İSTEYEN durumlar için.

   Ölçüldü: 123 belgenin 121'i "Onaylandı". Her satıra yeşil rozet basınca rozet hiçbir bilgi
   taşımıyor ve gözden geçirilmeyi bekleyen 2 belge listede kayboluyordu. Onaylanmış belge artık
   sessiz bir işaret taşıyor; sesli olan yalnız istisna. */
export default function StatusBadge({ status, label }: { status: string; label: string }) {
  if (status === "approved") {
    return (
      <span className="state-quiet" title={label}>
        <span aria-hidden="true">✓</span> {label}
      </span>
    );
  }
  const tone = status === "needs_human_review" ? "warn" : "info";
  return <span className={"badge " + tone}>{label}</span>;
}
