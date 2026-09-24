import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ChatPreviewResponse, ProvidersResponse } from "../../api/contract";
import { renderApp, stubApi, summary } from "../../test/harness";
import { ChatPanel } from "./ChatPanel";
import { ConsentDialog } from "./ConsentDialog";

const preview: ChatPreviewResponse = {
  provider: "claude_cli",
  preview_hash: "h-1",
  destination: "Anthropic (Claude)",
  sources: [{ id: "S1", doc_id: "d1", unit_id: "u1", label: "Deneme.docx · Madde 2", excerpt: "Kira <PERSON_1> adına ödenir." }],
  sent_text: "[S1] document 1, part 2\nKira <PERSON_1> adına ödenir.\n\nSoru: Kira kime ödenir?",
  context_chars: 1284,
};

describe("ConsentDialog", () => {
  it("keeps 'Gönder' disabled until the checkbox is ticked", async () => {
    const onConfirm = vi.fn();
    render(<ConsentDialog preview={preview} mode="consent" open onConfirm={onConfirm} onClose={() => undefined} />);
    const dialog = screen.getByRole("dialog", { name: "Gönderimi onaylayın" });
    expect(within(dialog).getByText("Anthropic (Claude)")).toBeInTheDocument();
    expect(within(dialog).getByRole("region", { name: "Gönderilecek metin" })).toHaveTextContent("Soru: Kira kime ödenir?");
    expect(within(dialog).getByText("1.284 karakter")).toBeInTheDocument();

    const send = within(dialog).getByRole("button", { name: "Gönder" });
    expect(send).toBeDisabled();
    await userEvent.click(send);
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByLabelText("Bu metnin Anthropic (Claude) tarafına gönderileceğini anladım"));
    expect(send).toBeEnabled();
    await userEvent.click(send);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("offers no send button when only inspecting a local payload", () => {
    render(<ConsentDialog preview={{ ...preview, provider: "ollama", destination: "Bu bilgisayar" }} mode="inspect" open onConfirm={() => undefined} onClose={() => undefined} />);
    const dialog = screen.getByRole("dialog", { name: "Gönderilecek metin" });
    expect(within(dialog).queryByRole("button", { name: "Gönder" })).toBeNull();
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
  });
});

const providers: ProvidersResponse = {
  default: "ollama",
  providers: [
    { id: "ollama", label: "Yerel (Ollama)", local: true, available: true, installed: null, compatible: null, authenticated: null, version: null, model: "qwen3.5:4b", login_command: null, problem: null },
    { id: "claude_cli", label: "Claude", local: false, available: true, installed: true, compatible: true, authenticated: true, version: "2.1", model: null, login_command: null, problem: null },
    { id: "codex_cli", label: "Codex", local: false, available: false, installed: true, compatible: true, authenticated: false, version: "0.44", model: null, login_command: "codex login", problem: "cli_login_required" },
  ],
};

describe("cloud chat", () => {
  it("cannot reach the provider without the previewed, consented payload", async () => {
    const doc = summary({ status: "approved", can: { review: true, approve: false, download: true, chat: true, decide: false } });
    const calls = stubApi({
      "GET /api/chat/providers": providers,
      "GET /api/settings": { default_mode: "mapping", chat_default_provider: "ollama", always_mask: [], never_mask: [] },
      "GET /api/documents": { documents: [doc] },
      "POST /api/chat/preview": preview,
      "POST /api/chat": { answer: "Kira <PERSON_1> adına ödenir [S1].", citations: preview.sources, provider: "claude_cli", elapsed_ms: 900 },
    });
    renderApp(<ChatPanel doc={doc} onFocusUnit={() => undefined} />);

    expect(await screen.findByText("codex login")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Codex/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Claude/ }));
    await userEvent.type(screen.getByLabelText("Soru"), "Kira kime ödenir?");
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));

    const dialog = await screen.findByRole("dialog", { name: "Gönderimi onaylayın" });
    expect(calls.filter((c) => c.url === "/api/chat/preview")).toHaveLength(1);
    expect(calls.some((c) => c.url === "/api/chat")).toBe(false);

    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Gönder" }));

    await waitFor(() => expect(calls.some((c) => c.url === "/api/chat")).toBe(true));
    const sent = calls.find((c) => c.url === "/api/chat")!;
    expect(sent.body).toMatchObject({ provider: "claude_cli", preview_hash: "h-1", doc_ids: ["d1"], question: "Kira kime ödenir?" });
    expect(await screen.findByRole("button", { name: "Kaynak S1: Deneme.docx · Madde 2" })).toBeInTheDocument();
  });

  it("previews and sends the identical history array for a follow-up question", async () => {
    const doc = summary({ status: "approved", can: { review: true, approve: false, download: true, chat: true, decide: false } });
    const calls = stubApi({
      "GET /api/chat/providers": providers,
      "GET /api/settings": { default_mode: "mapping", chat_default_provider: "ollama", always_mask: [], never_mask: [] },
      "GET /api/documents": { documents: [doc] },
      "POST /api/chat/preview": preview,
      "POST /api/chat": (body: unknown) => ({
        answer: `Yanıt: ${(body as { question: string }).question} [S1]`,
        citations: preview.sources,
        provider: (body as { provider: string }).provider,
        elapsed_ms: 400,
      }),
    });
    renderApp(<ChatPanel doc={doc} onFocusUnit={() => undefined} />);

    // First question stays local, so there is an earlier exchange in the conversation.
    await screen.findByText("codex login");
    await userEvent.type(screen.getByLabelText("Soru"), "Kira ne kadar?");
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));
    await screen.findByText(/Yanıt: Kira ne kadar\?/);

    // The follow-up goes to the cloud: preview and send must carry the same history.
    await userEvent.click(screen.getByRole("button", { name: "Sağlayıcıyı değiştir" }));
    await userEvent.click(screen.getByRole("radio", { name: /Claude/ }));
    await userEvent.type(screen.getByLabelText("Soru"), "Ödeme hangi gün?");
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));
    const dialog = await screen.findByRole("dialog", { name: "Gönderimi onaylayın" });
    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Gönder" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/chat")).toHaveLength(2));

    const previewBody = calls.find((c) => c.url === "/api/chat/preview")!.body as { history: unknown[] };
    const chatBody = calls.filter((c) => c.url === "/api/chat")[1].body as { history: unknown[]; provider: string };
    expect(chatBody.provider).toBe("claude_cli");
    expect(previewBody.history).toHaveLength(2);
    expect(chatBody.history).toEqual(previewBody.history);
    expect(previewBody.history).toEqual([
      { role: "user", content: "Kira ne kadar?" },
      { role: "assistant", content: "Yanıt: Kira ne kadar? [S1]" },
    ]);
  });

  it("drops a pending consent when the provider changes", async () => {
    const doc = summary({ status: "approved", can: { review: true, approve: false, download: true, chat: true, decide: false } });
    const calls = stubApi({
      "GET /api/chat/providers": providers,
      "GET /api/settings": { default_mode: "mapping", chat_default_provider: "ollama", always_mask: [], never_mask: [] },
      "GET /api/documents": { documents: [doc] },
      "POST /api/chat/preview": preview,
    });
    renderApp(<ChatPanel doc={doc} onFocusUnit={() => undefined} />);
    await screen.findByText("codex login");
    await userEvent.click(screen.getByRole("radio", { name: /Claude/ }));
    await userEvent.type(screen.getByLabelText("Soru"), "Kira kime ödenir?");
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));
    await screen.findByRole("dialog", { name: "Gönderimi onaylayın" });

    // jsdom does not make the page inert behind a modal, which lets the test change the provider.
    await userEvent.click(screen.getByRole("radio", { name: /Yerel/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.some((c) => c.url === "/api/chat")).toBe(false);
  });
});
