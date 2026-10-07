import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ProviderStatus } from "../../api/contract";
import { providerProblemText } from "../../copy/tr";
import { ProviderPicker } from "../chat/ProviderPicker";
import { ProviderCard } from "./ProviderCard";

// What GET /api/chat/providers reports on Windows for the two CLI providers (backend
// chat/providers.py): unavailable, nothing probed, problem "unsupported_os".
const onWindows = (id: "claude_cli" | "codex_cli", label: string): ProviderStatus => ({
  id,
  label,
  local: false,
  available: false,
  installed: null,
  compatible: null,
  authenticated: null,
  version: null,
  model: null,
  login_command: null,
  problem: "unsupported_os",
});

const ollama: ProviderStatus = {
  id: "ollama",
  label: "Yerel (Ollama)",
  local: true,
  available: true,
  installed: null,
  compatible: null,
  authenticated: null,
  version: null,
  model: "qwen3.5:4b",
  login_command: null,
  problem: null,
};

describe("chat provider status on Windows", () => {
  it("the settings card says why Claude cannot be used", () => {
    render(<ProviderCard provider={onWindows("claude_cli", "Claude")} />);
    expect(screen.getByText("Kullanılamıyor")).toBeInTheDocument();
    expect(screen.getByText(providerProblemText.unsupported_os)).toBeInTheDocument();
    expect(screen.queryByText("Beklenmeyen bir yanıt alındı. Sayfayı yenileyip tekrar deneyin.")).toBeNull();
  });

  it("the picker disables the CLI providers and keeps Ollama selectable", () => {
    const providers = [ollama, onWindows("claude_cli", "Claude"), onWindows("codex_cli", "Codex")];
    render(<ProviderPicker providers={providers} value="ollama" onChange={() => undefined} />);
    expect(screen.getByRole("radio", { name: /Claude/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Codex/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Yerel \(Ollama\)/ })).toBeEnabled();
    expect(screen.getAllByText(providerProblemText.unsupported_os)).toHaveLength(2);
  });
});
