// Installs the in-browser mock backend. Loaded only when VITE_MOCK=1 or the URL carries ?mock=1.
import { setPageImageResolver, setTransport } from "../client";
import { pageSvg, svgDataUrl } from "./pages";
import { mockFetch, requestLog } from "./router";
import { getDoc } from "./store";

export function installMock(): void {
  setTransport(mockFetch);
  const cache = new Map<string, string>();
  setPageImageResolver((docId, index) => {
    const key = `${docId}:${index}`;
    const cached = cache.get(key);
    if (cached) return cached;
    const doc = getDoc(docId);
    const page = doc?.pages.find((p) => p.index === index);
    if (!doc || !page || doc.mode === "destructive") return "data:,";
    const url = svgDataUrl(pageSvg(doc, page));
    cache.set(key, url);
    return url;
  });
  // Lets end-to-end tests assert what was (and was not) sent.
  (window as unknown as { __screenwallMock?: unknown }).__screenwallMock = { requests: requestLog };
}
