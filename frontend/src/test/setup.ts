import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { setTransport } from "../api/client";
import { resetConversations } from "../features/chat/chatStore";

afterEach(() => {
  cleanup();
  setTransport(null);
  resetConversations();
  window.getSelection()?.removeAllRanges();
});

// jsdom has no modal dialog behaviour or layout; give the app the parts it relies on.
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.removeAttribute("open");
  this.dispatchEvent(new Event("close"));
};
Element.prototype.scrollIntoView = function scrollIntoView() {};
