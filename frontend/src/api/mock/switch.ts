// Decides, once per page load, whether the in-browser mock backend replaces the real API.
const KEY = "screenwall.mock";
let cached: boolean | null = null;

function detect(): boolean {
  if (import.meta.env.VITE_MOCK === "1") return true;
  if (typeof window === "undefined") return false;
  const flag = new URLSearchParams(window.location.search).get("mock");
  try {
    if (flag === "1" || flag === "0") window.sessionStorage.setItem(KEY, flag);
    return (flag ?? window.sessionStorage.getItem(KEY)) === "1";
  } catch {
    return flag === "1";
  }
}

export function isMockEnabled(): boolean {
  if (cached === null) cached = detect();
  return cached;
}
