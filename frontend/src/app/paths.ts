export const CHAT_SEGMENT = "sohbet";

export const docPath = (id: string, chat = false) =>
  `/d/${encodeURIComponent(id)}${chat ? `/${CHAT_SEGMENT}` : ""}`;
