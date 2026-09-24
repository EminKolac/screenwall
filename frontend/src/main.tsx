import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/base.css";
import { App } from "./app/App";
import { isMockEnabled } from "./api/mock/switch";

async function boot() {
  // The mock backend is a separate chunk; it only loads with VITE_MOCK=1 or ?mock=1.
  if (isMockEnabled()) {
    const { installMock } = await import("./api/mock");
    installMock();
  }
  const root = document.getElementById("root");
  if (!root) throw new Error("Missing #root element");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
