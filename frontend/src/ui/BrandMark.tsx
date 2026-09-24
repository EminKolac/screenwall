/** Screenwall mark: a sheet whose first line is already masked. */
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" focusable="false" style={{ flex: "none" }}>
      <rect x="1" y="1" width="18" height="18" rx="5" fill="var(--accent)" />
      <rect x="5" y="6.5" width="10" height="2.4" rx="1.2" fill="var(--on-accent)" />
      <rect x="5" y="11.1" width="6.5" height="2.4" rx="1.2" fill="var(--on-accent)" opacity="0.55" />
    </svg>
  );
}
