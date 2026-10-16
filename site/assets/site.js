/* Screenwall site: TR <-> EN toggle (Turkish is in the HTML, English lives here) and the copy button.
   No cookies, no tracking; the language choice is kept in localStorage only if the browser allows it. */
(function () {
  "use strict";
  const EN = {
    "skip": "Skip to content",
    "nav.how": "How it works", "nav.tests": "Tests", "nav.dl": "Download",
    "eyebrow": "For macOS · Turkish and English",
    "h1": "Mask first. Then ask.",
    "lead": "Mask sensitive data in your company documents on your own computer before asking Claude or ChatGPT about them. Customer and signatory names, emails, IBANs and tax numbers become labels; the real values stay on your computer and you approve the outgoing text first.",
    "cta.dl": "Watch the film", "cta.gh": "Source on GitHub",
    "meta": "macOS 14 or later · Apple Silicon and Intel · requires Ollama",
    "release.pending": "v0.1.2 is available. Find the DMG and ZIP packages with installation notes below.",
    "cta.dmg": "Download for macOS · DMG",
    "film": "50-second film (in Turkish). All companies and people are fictional.",
    "deck": "Download the project deck (PPTX)",
    "p.k": "The problem",
    "p.h": 'You want to ask Claude or ChatGPT about company documents. <span class="coral">But they contain customer, signatory and bank details.</span>',
    "p.sub": "Sending that text to the cloud as it is is a data-protection and confidentiality risk. Screenwall masks it first; only labelled text goes to Claude or ChatGPT, and only with your approval.",
    "how.k": "How it works", "how.h": "Five steps. Detection and auditing happen on this computer.",
    "s1.h": "Upload the document.", "s1.p": "PDF, Word or Excel. It is processed on this computer and not sent anywhere.",
    "s2.h": "Sensitive data is found and labelled.",
    "s2.p": 'Company names, signatories, emails, IBANs and tax numbers become labels such as <span class="tag">&lt;ORG_1&gt;</span>, <span class="tag">&lt;PERSON_1&gt;</span>. Amounts and the text stay readable.',
    "s3.h": "A local LLM audits it.", "s3.p": "The masked copy is checked by rules and a local LLM (Qwen 3.5 4B) running in Ollama. Both must report it clean.",
    "s4.h": "When in doubt, the user decides.", "s4.p": "If the auditor is unsure, the document is not approved automatically. Review it, mask it or leave it; the final copy must still pass the local LLM audit.",
    "s5.h": "Use the masked document.", "s5.p": "After approval, download a PDF generated from the masked text or ask the local LLM. Optional chat with Claude (Claude Code) or ChatGPT (Codex CLI) shows the outgoing text for approval with every question.",
    "shot.alt": "Screenwall review screen: the auditor is unsure about 'A. Yılmaz'; Mask and Leave buttons are shown.",
    "shot.cap": "Step 4: the decision screen when the auditor is unsure. Sample data.",
    "pr.k": "Privacy by design", "pr.h": "Your document, your computer, your decision.",
    "c1.h": "Runs on this computer", "c1.p": "Detection, masking and auditing happen on this computer. The original document never leaves it.",
    "c2.h": "Stops when unsure", "c2.p": "If it is not sure, it does not approve the document; it asks you.",
    "c3.h": "Shows before it sends", "c3.p": "If anything is to go to the cloud, it first shows you the exact text and asks for explicit consent.",
    "c4.h": "Stores no API keys", "c4.p": "The optional cloud chat runs through your own Claude Code or Codex (ChatGPT) login; Screenwall stores no API keys.",
    "t.k": "Tests", "t.h": "We tested it on sample documents.",
    "t1.l": "critical items, strict count", "t1.p": "472 of 489 critical values were caught in the 60-document development set. This measured rules and detection, with the local LLM off.",
    "t2.l": "documents leaked data", "t2.p": "With the local LLM audit on, no sensitive data leaked into an approved output in 72 stress documents.",
    "t3.l": "unnecessary masking", "t3.p": "It masked something in 11 of 40 business sentences that contain no sensitive data. A known flaw we are working on.",
    "t.note": 'Our own measurements, using the development set that helped tune the rules. Our own scorer reports 1555/1555 on the same set. In the stress test with the local LLM on, 59 of 62 safe documents were approved; three remained in review. There is no independent, unseen test set yet. All numbers and methods: <a href="https://github.com/EminKolac/screenwall/blob/main/docs/SCORECARD.md">SCORECARD</a>.',
    "t.limits": "Masking is imperfect. Uppercase names within sentences, some addresses and details such as occupation, education or salary may remain visible. Review the masked copy before sharing it.",
    "dl.k": "macOS package", "dl.h": "Download Screenwall.",
    "dl.pending": "Recommended installation: open the DMG and drag Screenwall into Applications. The environment is prepared on first launch; the interface opens in your browser.",
    "r1": "macOS 14 (Sonoma) or later; Apple Silicon and Intel.",
    "r2": '<a href="https://ollama.com/download">Ollama</a> and the qwen3.5:4b model are required (about 3.4 GB). If Ollama is installed, the model downloads on first launch. Without Ollama, documents can be masked but cannot be approved, downloaded or used for chat.',
    "r3": "The app is not signed by Apple, so macOS warns on first launch. Right-click the app and choose Open; on macOS 15 and later use System Settings › Privacy & Security › Open Anyway. If macOS offers to install developer tools, choose Cancel; they are not needed.",
    "r4": "Initial setup and setup after a new version may require internet access. Optional Tesseract is needed to read scanned PDF pages.",
    "r5": "Document approval with Ollama has not yet been tested on Intel Macs; the local LLM audit runs on the CPU and may be slower.",
    "term.h": "Alternative downloads and installation notes.",
    "copy": "Copy", "copied": "Copied",
    "term.n": '<a href="https://github.com/EminKolac/screenwall/releases/latest/download/Screenwall-macOS.zip">ZIP package</a> · <a href="https://github.com/EminKolac/screenwall/releases/latest/download/SHA256SUMS.txt">SHA256 checksums</a>',
    "term.docs": '<a href="https://github.com/EminKolac/screenwall#indir">Installation guide</a> · <a href="https://github.com/EminKolac/screenwall/releases/latest">Release notes</a>',
    "made": "Today, Claude chat uses your own Claude Code login, and ChatGPT chat uses your Codex CLI login. Screenwall does not call the Claude API directly. We plan to build an API integration that preserves user approval; it is not an existing feature.",
    "f.priv": "Privacy", "f.nocookie": "This site uses no cookies and no tracking.",
    "f.owner": "Screenwall is a product of", "f.owner2": ".", "f.contact": "Contact:",
    "f.incorporated": "Incorporated: 5 August 2026.",
    "f.emailstate": "",
  };
  const TR = {};
  const nodes = document.querySelectorAll("[data-i18n],[data-i18n-html],[data-i18n-alt]");
  nodes.forEach((el) => {                       // remember the Turkish text that ships in the HTML
    if (el.dataset.i18n) TR[el.dataset.i18n] = el.textContent;
    if (el.dataset.i18nHtml) TR[el.dataset.i18nHtml] = el.innerHTML;
    if (el.dataset.i18nAlt) TR[el.dataset.i18nAlt] = el.getAttribute("alt");
  });
  TR.copied = "Kopyalandı";
  let lang = "tr";

  function apply(l) {
    const d = l === "en" ? EN : TR;
    nodes.forEach((el) => {
      if (el.dataset.i18n && d[el.dataset.i18n] !== undefined) el.textContent = d[el.dataset.i18n];
      if (el.dataset.i18nHtml && d[el.dataset.i18nHtml] !== undefined) el.innerHTML = d[el.dataset.i18nHtml];
      if (el.dataset.i18nAlt && d[el.dataset.i18nAlt] !== undefined) el.setAttribute("alt", d[el.dataset.i18nAlt]);
    });
    document.documentElement.lang = l;
    document.title = l === "en" ? "Screenwall — Mask first. Then ask." : "Screenwall — Önce maskele. Sonra sor.";
    const description = l === "en"
      ? "Screenwall masks customer, signatory, bank and tax details in company documents (PDF, Word, Excel) on your computer. Only labelled text goes to Claude or ChatGPT."
      : "Screenwall, şirket dokümanlarındaki (PDF, Word, Excel) müşteri, yetkili, banka ve vergi bilgilerini bilgisayarınızda maskeler. Claude ya da ChatGPT'ye yalnız etiketli metin gider.";
    document.querySelector('meta[name="description"]').setAttribute("content", description);
    document.querySelector('meta[property="og:title"]').setAttribute("content", document.title);
    document.querySelector('meta[property="og:description"]').setAttribute("content", description);
    const b = document.getElementById("lang");
    b.textContent = l === "en" ? "TR" : "EN";
    b.setAttribute("aria-label", l === "en" ? "Türkçeye geç" : "Switch to English");
    lang = l;
  }

  function saved() { try { return localStorage.getItem("sw-lang"); } catch (e) { return null; } }
  function save(l) { try { localStorage.setItem("sw-lang", l); } catch (e) { /* storage blocked: fine */ } }

  const hash = location.hash.replace("#", "");
  const initial = hash === "en" || hash === "tr" ? hash
    : saved() || ((navigator.language || "tr").toLowerCase().startsWith("tr") ? "tr" : "en");
  if (initial === "en") apply("en");

  document.getElementById("lang").addEventListener("click", () => {
    const next = lang === "en" ? "tr" : "en";
    apply(next);
    save(next);
  });

  const copy = document.getElementById("copy");
  const cmd = document.getElementById("cmd");
  if (copy && cmd) copy.addEventListener("click", () => {
    const text = cmd.textContent;
    const done = () => { copy.textContent = (lang === "en" ? EN : TR).copied; setTimeout(() => { copy.textContent = (lang === "en" ? EN : TR).copy; }, 1600); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => selectCmd());
    } else selectCmd();
  });
  function selectCmd() {
    if (!cmd) return;
    const r = document.createRange();
    r.selectNodeContents(cmd);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
})();
