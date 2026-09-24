/** A sheet whose personal details are already masked; drawn with theme tokens. */
export function EmptyArt() {
  return (
    <svg width="168" height="128" viewBox="0 0 168 128" aria-hidden="true" focusable="false">
      <rect x="34" y="10" width="100" height="110" rx="7" fill="var(--surface)" stroke="var(--rule-strong)" />
      <rect x="46" y="26" width="52" height="6" rx="3" fill="var(--ink)" opacity="0.8" />
      <rect x="46" y="42" width="30" height="10" rx="3" fill="var(--ok-bg)" stroke="var(--ok-stroke)" />
      <rect x="80" y="44" width="40" height="5" rx="2.5" fill="var(--rule-strong)" />
      <rect x="46" y="60" width="74" height="5" rx="2.5" fill="var(--rule-strong)" />
      <rect x="46" y="73" width="26" height="5" rx="2.5" fill="var(--rule-strong)" />
      <rect x="76" y="70" width="36" height="10" rx="3" fill="var(--sug-bg)" stroke="var(--sug-stroke)" strokeDasharray="3 2" />
      <rect x="46" y="88" width="22" height="10" rx="3" fill="var(--ok-bg)" stroke="var(--ok-stroke)" />
      <rect x="72" y="90" width="44" height="5" rx="2.5" fill="var(--rule-strong)" />
      <circle cx="130" cy="104" r="16" fill="var(--accent)" />
      <path d="m123 104 5 5 9-10" fill="none" stroke="var(--on-accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
