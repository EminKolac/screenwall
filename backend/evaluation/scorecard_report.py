"""Scorecard gates (plan §3 hard gates) and the Markdown rendering of `scorecard.json`."""
from __future__ import annotations

from evaluation.scorecard_common import EMPTY_TERM_LISTS_SHA256, LLM_SECTIONS

PASS, FAIL, NOT_MEASURED = "PASS", "FAIL", "NOT_MEASURED"
LLM_GATE = "LLM denetçisi gerçekten çalıştı (süre + sıfır LLM hatası)"


def fmt_frac(f: dict | None) -> str:
    return f"{f['numerator']}/{f['denominator']}" if f else "—"


def _num(v) -> str:
    return "—" if v is None else str(v)


def _ok(section: dict | None) -> bool:
    return bool(section) and section.get("status") == "ok"


def _gate(name: str, target: str, value, verdict: str, note: str = "") -> dict:
    return {"gate": name, "target": target, "value": value, "verdict": verdict, "note": note}


# ---------------------------------------------------------------------------------- gates

def _gate_strict(s: dict | None, key: str, name: str, target: str, check) -> dict:
    if not _ok(s) or not s.get("complete"):
        return _gate(name, target, None, NOT_MEASURED, "strict bölümü tam koşulmadı")
    f = s[key]
    return _gate(name, target, fmt_frac(f), PASS if check(f) else FAIL)


def _gate_subset(g: dict | None) -> dict:
    name, target = "v5 20-belge alt kümesinde kritik recall (Fable skorlayıcısı)", "1.0"
    sub = (g or {}).get("subset20") or {}
    if not _ok(g) or sub.get("documents") != 20 or sub.get("records") != sub.get("processed"):
        return _gate(name, target, None, NOT_MEASURED, "20 belgenin hepsi işlenmedi")
    f = sub["critical_recall"]
    passed = bool(f["denominator"]) and f["numerator"] == f["denominator"]
    return _gate(name, target, fmt_frac(f), PASS if passed else FAIL)


def _docs(block: dict) -> str:
    return f"{block['documents']}/{block['expected_documents']} belge"


def _gate_regression(g: dict | None) -> dict:
    name = "Fable skorlayıcısı, holdout kritik recall: Faz 0 tabanından geri gidiş yok"
    if not _ok(g):
        return _gate(name, ">= taban", None, NOT_MEASURED, "gold bölümü koşulmadı")
    full = g["full"]
    value = f"{fmt_frac(full['critical_recall'])} ({_docs(full)})"
    note = "otomatik taban yok; Faz 0 taban skor kartıyla karşılaştırın"
    if not g.get("complete"):
        note = f"kısmi: {_docs(full)}; tam koşuyla ve tabanla karşılaştırılamaz"
    return _gate(name, ">= taban", value, NOT_MEASURED, note)


def _llm_passed(section: dict | None) -> bool:
    evidence = (section or {}).get("llm_evidence") or {}
    return evidence.get("passed") is True


def _gates_stress(s: dict | None, llm: str) -> list[dict]:
    specs = [
        ("Stres: onaylı çıktıya sızıntı (canlı LLM)", "0/72", "leaks_approved",
         lambda f: f["numerator"] == 0 and f["denominator"] == 72),
        ("Stres: güvenli teslim (canlı LLM)", ">= 59/62", "safe_delivery",
         lambda f: f["denominator"] == 62 and f["numerator"] >= 59),
    ]
    out = []
    for name, target, key, check in specs:
        if not _ok(s) or not s.get("complete"):
            out.append(_gate(name, target, None, NOT_MEASURED, "stres bölümü tam koşulmadı"))
        elif llm != "on":
            out.append(_gate(name, target, fmt_frac(s[key]), NOT_MEASURED,
                             "kapı --llm on ister; bu koşu yalnız sezgisel denetçiyle"))
        elif not check(s[key]):
            out.append(_gate(name, target, fmt_frac(s[key]), FAIL))  # a failure stands anyway
        elif not _llm_passed(s):
            out.append(_gate(name, target, fmt_frac(s[key]), NOT_MEASURED,
                             "LLM her belgeyi denetlemedi; 'canlı LLM' ile geçti denemez "
                             f"(bkz. {LLM_GATE})"))
        else:
            out.append(_gate(name, target, fmt_frac(s[key]), PASS))
    return out


def _gate_llm_ran(sections: dict, llm: str) -> dict:
    name, target = LLM_GATE, ">= 1.0 sn medyan ve 0 LLM hatası"
    if llm != "on":
        return _gate(name, target, None, NOT_MEASURED, "--llm off")
    evidence = [(n, sections[n]["llm_evidence"]) for n in LLM_SECTIONS
                if _ok(sections.get(n)) and sections[n].get("llm_evidence")]
    if not evidence:
        return _gate(name, target, None, NOT_MEASURED, "LLM kullanan bölüm koşulmadı")
    value = ", ".join(f"{n} {e['median_seconds_per_file']} sn, "
                      f"{_num(e.get('llm_failures'))} LLM hatası" for n, e in evidence)
    problems = []  # a missing key counts as a problem: no evidence, no pass
    for n, e in evidence:
        if not e.get("plausible"):
            problems.append(f"{n}: süre şüpheli")
        if not e.get("every_audit_had_llm"):
            problems.append(f"{n}: {_num(e.get('documents_not_fully_llm_audited'))} belge "
                            "LLM kararı almadan denetlendi")
    return _gate(name, target, value, FAIL if problems else PASS, "; ".join(problems))


def evaluate_gates(sections: dict, llm: str) -> list[dict]:
    strict = sections.get("strict")
    return [
        _gate_strict(strict, "critical_recall", "Katı kritik recall (60 belge, allow-list yok)",
                     ">= 472/489", lambda f: f["denominator"] == 489 and f["numerator"] >= 472),
        _gate_regression(sections.get("gold")),
        _gate_subset(sections.get("gold")),
        _gate_strict(strict, "canary_escapes", "Canary kaçağı (bare + contextual)", "0/32",
                     lambda f: f["numerator"] == 0 and f["denominator"] == 32),
        *_gates_stress(sections.get("stress"), llm),
        _gate_llm_ran(sections, llm),
    ]


# ------------------------------------------------------------------------------- markdown

def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _counts(d: dict | None) -> str:
    return " · ".join(f"{k} {v}" for k, v in sorted((d or {}).items(), key=lambda kv: -kv[1])) \
        or "—"


def _not_ok(title: str, section: dict) -> str:
    detail = section.get("reason") or section.get("error") or ""
    return f"{title}\n\nDurum: **{section.get('status')}** {detail}".rstrip()


def _llm_line(card: dict) -> str:
    cfg, llm_cfg = card["config"], card["config"].get("llm_settings") or {}
    ran = [n for n in LLM_SECTIONS
           if n in card["sections"] and card["sections"][n].get("status") != "skipped"]
    if not ran:
        return (f"- LLM denetçisi: kullanılmadı — denetçiyi çalıştıran bölüm (gold, stress) "
                f"koşulmadı; `--llm {cfg['llm']}` bu koşuda etkisiz")
    return (f"- LLM denetçisi: **{cfg['llm']}** ({', '.join(ran)} bölümünde; "
            f"auditor_provider={llm_cfg.get('auditor_provider')}, "
            f"require_llm_auditor={llm_cfg.get('require_llm_auditor')}, "
            f"model={llm_cfg.get('auditor_model') or '—'})")


def _term_lists_line(sections: dict) -> str:
    recs = [(n, s["term_lists"]) for n, s in sections.items() if s.get("term_lists")]
    if not recs:
        return "- Terim listeleri (allow/deny): kayıt yok"
    sizes = " · ".join(f"{n} {t['allow']}/{t['deny']}" for n, t in recs)
    hashes = {t["sha256"] for _, t in recs}
    digest = (f"sha256 `{next(iter(hashes))[:16]}…`" if len(hashes) == 1
              else "sha256 bölüme göre farklı (JSON'a bakın)")
    empty = " = boş listeler" if hashes == {EMPTY_TERM_LISTS_SHA256} else ""
    return f"- Terim listeleri (allow/deny, motora giden): {sizes} · {digest}{empty}"


def _completeness_banner(card: dict) -> list[str]:
    if card["complete"]:
        return []
    skipped = card.get("skipped") or []
    named = ", ".join(f"{s['section']} ({s['reason']})" for s in skipped)
    partial = card["config"]["limit"] or any(
        s.get("status") == "error" or (s.get("status") == "ok" and s.get("complete") is not True)
        for s in card["sections"].values())
    if not partial:
        return ["", f"> **EKSİK KOŞU** — atlanan: {named}. Koşulan bölümler tamdır; "
                    "atlananlar bu koşuda ölçülmedi."]
    tail = f" Atlanan: {named}." if named else ""
    return ["", "> **KISMİ KOŞU** — `--limit`, hatalı ya da eksik bölüm var; bu sayılar tam "
                f"koşularla karşılaştırılamaz.{tail}"]


def _header(card: dict) -> str:
    cfg, git = card["config"], card["config"].get("git") or {}
    dirty = git.get("uncommitted_paths")
    lines = [
        f"# Fable skor kartı — {card['run_id']}", "",
        f"- Zaman: {card['started_at']} → {card['finished_at']}",
        f"- Kod: {git.get('branch') or '?'} @ {(git.get('commit') or '?')[:10]}"
        + (f" (+{dirty} commit edilmemiş yol)" if dirty else ""),
        f"- Kaynak parmak izi: app/ `{(cfg.get('app_source_sha256') or '?')[:16]}` · "
        f"evaluation/ `{(cfg.get('evaluation_source_sha256') or '?')[:16]}` "
        "(results/ ve önbellekler hariç)",
        _llm_line(card),
        _term_lists_line(card["sections"]),
        f"- Bölümler: {', '.join(cfg['sections'])} · limit: {cfg['limit'] or 'yok'} · "
        f"gerçek belge: {cfg['real']}",
        f"- Korpus: `{cfg['corpus']}`",
    ]
    return "\n".join(lines + _completeness_banner(card))


def _gates_md(gates: list[dict]) -> str:
    rows = [[g["gate"], g["target"], _num(g["value"]), g["verdict"], g["note"]] for g in gates]
    return "## Kapılar (plan §3)\n\n" + _table(["Kapı", "Hedef", "Değer", "Sonuç", "Not"], rows)


def _no_mask_row(full: dict, sub: dict) -> list:
    if full.get("no_mask_violations") is None:
        return ["NO_MASK ihlali", "— (kirli: allow-list açıktı)", "—",
                "yerine (b) must_keep satırı"]
    return ["NO_MASK ihlali (liste yok, dürüst)", fmt_frac(full["no_mask_violations"]),
            fmt_frac(sub["no_mask_violations"]), "pipeline, liste yok"]


def _llm_audits_cell(block: dict) -> str:
    a = block.get("llm_audits") or {}
    if not a:
        return "—"
    return f"{a['audits']} / {a['llm_ok']} / {a['llm_failed']}"


def _gold_rows(full: dict, sub: dict) -> list[list]:
    def both(key, fmt=_num):
        return [fmt(full[key]), fmt(sub[key])]

    by_fmt = " · ".join(f"{k} {fmt_frac(v)}" for k, v in full["critical_recall_by_format"].items())
    return [
        ["Kritik recall (mention × format)", *both("critical_recall", fmt_frac), "pipeline"],
        ["Kritik mention, metinde bulunamayan (recall'dan hariç)",
         *both("critical_not_located"), "çıkarım"],
        [f"Kritik recall, format başına ({full['documents']} belge)", by_fmt, "", "pipeline"],
        ["Mention recall", *both("mention_recall"), "pipeline"],
        ["Entity recall", *both("entity_recall"), "pipeline"],
        ["Karakter recall", *both("char_recall"), "detect"],
        ["Karakter precision (yaklaşık)", *both("char_precision_approx"), "detect"],
        ["F2", *both("f2"), "detect"],
        ["Kısmi sızıntı (mention)", *both("partial_leaks"), "pipeline"],
        ["Export'ta sızıntı", *both("leaked_in_export"), "pipeline export"],
        _no_mask_row(full, sub),
        ["Belge / kayıt / işlenen",
         *[f"{b['documents']} / {b['records']} / {b['processed']}" for b in (full, sub)], ""],
        ["Durumlar", _counts(full["status_counts"]), _counts(sub["status_counts"]), ""],
        ["Denetim / LLM kararı / LLM hatası", _llm_audits_cell(full), _llm_audits_cell(sub), ""],
        ["Medyan sn/dosya", *both("median_seconds_per_file"), ""],
    ]


def _llm_evidence_note(ev: dict) -> str:
    verdict = "geçti" if ev.get("passed") else "GEÇMEDİ"
    return (f"- LLM kanıtı ({verdict}): medyan {ev['median_seconds_per_file']} sn/dosya "
            f"({'makul' if ev['plausible'] else 'ŞÜPHELİ'}); {_num(ev.get('llm_failures'))} "
            f"denetim LLM kararı almadı ({_num(ev.get('documents_not_fully_llm_audited'))} belge); "
            f"beklenen: {ev['expected']}.")


def _pipeline_lists(terms: dict) -> str:
    if not terms:
        return "terim listesi kaydı yok"
    if terms.get("allow") == 0 and terms.get("deny") == 0:
        return ("terim listeleri kapalı (allow 0 / deny 0: varsayılan allow-list, "
                "ALLOW_TERMS / DENY_TERMS ve kullanıcı listeleri yok)")
    return f"terim listeleri AÇIK (allow {terms.get('allow')} / deny {terms.get('deny')})"


def _gold_md(g: dict | None) -> str:
    title = "## (a) Fable GoldBench skorlayıcısı — holdout (pdf + docx + xlsx)"
    if not g:
        return ""
    if g["status"] != "ok":
        return _not_ok(title, g)
    full, sub = g["full"], g["subset20"]
    honest = full.get("no_mask_violations") is not None
    notes = [
        f"- 20 belgelik alt küme: {sub['rule']}. Bugünkü sıra bu kurala uyuyor: "
        f"{'evet' if sub['rule_matches_holdout_order'] else 'HAYIR'}.",
        "- **detect**: `engine.detect()` orijinal metinde (yayılım, tablo geçişi, allow-list yok). "
        "**pipeline**: değer `run_pipeline` çıktısında yok; "
        f"{_pipeline_lists(g.get('term_lists') or {})}.",
        "- Kritik recall yalnız çıkarılan metinde bulunan mention'ları sayar; bulunamayanlar "
        "ayrı satırda.",
        "- NO_MASK satırı liste olmadan ölçülür, yani dürüsttür: must_keep terimlerini koruyan "
        "bir allow-list yok. Aynı soruyu motor düzeyinde (b) bölümündeki must_keep satırı ölçer."
        if honest else
        "- NO_MASK sayısı verilmez: pipeline allow-list ile koştu ve varsayılan liste her "
        "must_keep terimini içerir. Dürüst aşırı maskeleme sayısı (b) bölümündeki must_keep "
        "satırıdır.",
    ]
    if g.get("llm_evidence"):
        notes.append(_llm_evidence_note(g["llm_evidence"]))
    table = _table(["Ölçüm", f"Holdout ({_docs(full)})", f"v5 alt kümesi ({_docs(sub)})",
                    "Ölçüm yolu"], _gold_rows(full, sub))
    return f"{title}\n\nLLM: {g['llm']}\n\n{table}\n\n" + "\n".join(notes)


def _strict_md(s: dict | None) -> str:
    title = "## (b) Katı skorlayıcı (V2 kopyası, motor allow-list olmadan)"
    if not s:
        return ""
    if s["status"] != "ok":
        return _not_ok(title, s)
    rows = [
        ["Kritik recall (partial guard)", fmt_frac(s["critical_recall"])],
        ["Literal kritik recall", fmt_frac(s["literal_critical_recall"])],
        ["Tüm mention recall", fmt_frac(s["recall"])],
        ["Canary kaçağı, bare + contextual (düşük iyi)",
         f"{fmt_frac(s['canary_escapes'])} (bare {fmt_frac(s['canary_escapes_bare'])} · "
         f"contextual {fmt_frac(s['canary_escapes_contextual'])})"],
        ["Kritik canary kaçağı", fmt_frac(s["canary_escapes_critical"])],
        ["Nötr cümle değişimi (düşük iyi)", fmt_frac(s["neutral_changed"])],
        ["must_keep korunan, liste yok (yüksek iyi)", fmt_frac(s["must_keep_kept"])],
        ["İşlenemeyen belge", len(s["unprocessed_documents"])],
        ["sn/öğe", _num(s.get("seconds_per_item"))],
    ]
    note = (f"scorer.py sha256 `{s['scorer_sha256'][:16]}…` (testle sabit) · allow-list: "
            f"{s['allow_list']} · dış ağ: {s['external_network']}")
    return f"{title}\n\n{_table(['Ölçüm', 'Değer'], rows)}\n\n{note}"


def _stress_md(s: dict | None) -> str:
    title = "## (c) Stres — sabit dosyalar, tam pipeline"
    if not s:
        return ""
    if s["status"] != "ok":
        return _not_ok(title, s)
    title = f"## (c) Stres — {s['files']}/{s['corpus']['files']} sabit dosya, tam pipeline"
    rows = [
        ["Onaylı çıktıya sızıntı, kritik yanlış onay (düşük iyi)", fmt_frac(s["leaks_approved"])],
        ["Herhangi bir durumda sızıntı", fmt_frac(s["leaked_any_status"])],
        ["Güvenli teslim: safe_output → onaylı, sızıntısız", fmt_frac(s["safe_delivery"])],
        ["Fail-closed uyumu", fmt_frac(s["fail_closed_respected"])],
        ["İnsana yönlendirilen (temkinli)", s["routed_to_review"]],
        ["Gerçekten test edilen ve geçen", fmt_frac(s["actually_tested_pass"])],
        ["Durumlar", _counts(s["status_counts"])],
        ["Denetim / LLM kararı / LLM hatası", _llm_audits_cell(s)],
        ["Medyan sn/dosya (pipeline'a giren)", _num(s["median_seconds_per_file"])],
    ]
    ev = s.get("llm_evidence")
    note = f"LLM: **{s['llm']}**"
    if ev:
        note += (f" · kanıt: {'geçti' if ev.get('passed') else 'GEÇMEDİ'} (süre "
                 f"{'makul' if ev['plausible'] else 'ŞÜPHELİ'}, "
                 f"{_num(ev.get('llm_failures'))} LLM hatası; {ev['expected']})")
    note += f" · manifest sha256 `{s['corpus']['manifest_sha256'][:16]}…`"
    return f"{title}\n\n{_table(['Ölçüm', 'Değer'], rows)}\n\n{note}"


def _real_md(s: dict | None) -> str:
    title = "## (d) Gerçek belgeler — redaction_density"
    if not s:
        return ""
    if s["status"] != "ok":
        return _not_ok(title, s)
    fams = " · ".join(f"{k} {v} (%{round(100 * s['family_share'][k], 1)})"
                      for k, v in s["families"].items()) or "—"
    rows = [
        ["Ölçülen / istenen belge", f"{s['measured']} / {s['requested']}"],
        ["redaction_density (yer tutucu / 1000 karakter, tümü)", _num(s["redaction_density"])],
        ["Belge başına medyan yoğunluk", _num(s["redaction_density_median_doc"])],
        ["Karakter / yer tutucu", f"{s['extracted_chars']} / {s['placeholders']}"],
        ["Hata / boş çıkarım / atlanan", f"{s['errors']} / {s['empty_extraction']} / "
                                         f"{len(s['skipped'])}"],
        ["Yer tutucu aileleri", fams],
    ]
    docs = [[d["file"], d.get("pages", "—"), d.get("extracted_chars", "—"),
             d.get("placeholders", "—"), _num(d.get("redaction_density")), d["seconds"]]
            for d in s["per_document"]]
    per_doc = _table(["Dosya", "Sayfa", "Karakter", "Yer tutucu", "Yoğunluk", "sn"], docs)
    note = (f"Seçim: {s['selection_rule']}. Yol: {s['path']}. Precision hesaplanmaz "
            "(BENCHMARK_GUIDE §5.3).")
    return f"{title}\n\n{_table(['Ölçüm', 'Değer'], rows)}\n\n{per_doc}\n\n{note}"


def _timing_md(sections: dict) -> str:
    rows = [[name, s.get("status"), s.get("elapsed_seconds"),
             _num(s.get("median_seconds_per_file", s.get("seconds_per_item")))]
            for name, s in sections.items()]
    header = ["Bölüm", "Durum", "Geçen sn", "Medyan sn/dosya (strict: sn/öğe)"]
    return "## Süreler\n\n" + _table(header, rows)


NOTES = """## Notlar

- Rapor ham değer içermez: değerler yalnız vhash (sha256'nın ilk 16 hanesi) olarak geçer ve dosya
  yazılmadan önce bilinen bütün sentetik değerlere karşı taranır (`pii_scan`).
- Öğe başına ham çıktılar git dışındaki `backend/data/scorecard/<koşu>/` altındadır.
- (a) ve (c) mevcut koşucuları (`run_gold`, `run_stress`) kullanır, ama koşunun kendi storage
  kökünde ve terim listeleri kapalı (`term_lists=False`, boş ALLOW_TERMS / DENY_TERMS).
- `--llm on` = `auditor_provider=ollama` + `require_llm_auditor=True`; model yoksa koşu başlamadan
  durur. Koşu sırasında düşen her LLM çağrısı belge başına sayılır; LLM kapısı sıfır hata ister."""


def render_markdown(card: dict) -> str:
    s = card["sections"]
    parts = [_header(card), _gates_md(card["gates"]), _gold_md(s.get("gold")),
             _strict_md(s.get("strict")), _stress_md(s.get("stress")), _real_md(s.get("real")),
             _timing_md(s), NOTES]
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"
