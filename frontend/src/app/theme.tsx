import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePreference = "system" | "light" | "dark";

/** Same key is read by public/theme-init.js before first paint. */
export const THEME_KEY = "screenwall.theme";

function readPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function applyPreference(preference: ThemePreference) {
  const root = document.documentElement;
  if (preference === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", preference);
}

interface ThemeApi {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeApi | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    applyPreference(preference);
    try {
      window.localStorage.setItem(THEME_KEY, preference);
    } catch {
      // Storage can be unavailable (private mode); the theme still applies for this session.
    }
  }, [preference]);

  const api = useMemo(() => ({ preference, setPreference }), [preference]);
  return <ThemeContext.Provider value={api}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeApi {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme needs <ThemeProvider>");
  return ctx;
}
