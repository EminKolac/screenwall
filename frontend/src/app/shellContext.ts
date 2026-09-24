import { createContext, useContext } from "react";

export interface ShellApi {
  openSettings: () => void;
  openLibrary: () => void;
  /** True at ≤1040px, where the library becomes a drawer. */
  compact: boolean;
}

export const ShellContext = createContext<ShellApi>({
  openSettings: () => undefined,
  openLibrary: () => undefined,
  compact: false,
});

export function useShell(): ShellApi {
  return useContext(ShellContext);
}
