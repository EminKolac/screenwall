import type { StatusInfo } from "../types";

export default function StatusFlow({
  statuses,
  current,
}: {
  statuses: StatusInfo[];
  current: string;
}) {
  const idx = statuses.findIndex((s) => s.value === current);
  return (
    <div className="flow">
      {statuses.map((s, i) => (
        <div
          key={s.value}
          className={
            "step" +
            (s.value === current ? " current" : "") +
            (idx >= 0 && i <= idx ? " done" : "")
          }
          title={s.label}
        >
          {s.label}
        </div>
      ))}
    </div>
  );
}
