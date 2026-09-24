"""Scorecard gates (plan §3 hard gates) and the Markdown rendering of `scorecard.json`."""
from __future__ import annotations

PASS, FAIL, NOT_MEASURED = "PASS", "FAIL", "NOT_MEASURED"


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


def _gate_regression(g: dict | None) -> dict:
    value = fmt_frac(g["full"]["critical_recall"]) if _ok(g) else None
    return _gate("Fable skorlayıcısı, 60 belge: Faz 0 tabanından geri gidiş yok", ">= taban",
                 value, NOT_MEASURED, "otomatik taban yok; Faz 0 taban skor kartıyla karşılaştırın")


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
        else:
            out.append(_gate(name, target, fmt_frac(s[key]), PASS if check(s[key]) else FAIL))
    return out


def _gate_llm_ran(sections: dict, llm: str) -> dict:
    name, target = "LLM denetçisi gerçekten çalıştı (medyan sn/dosya)", ">= 1.0 sn"
    if llm != "on":
        return _gate(name, target, None, NOT_MEASURED, "--llm off")
    evidence = [(n, sections[n]["llm_evidence"]) for n in ("gold", "stress")
                if _ok(sections.get(n)) and sections[n].get("llm_evidence")]
    if not evidence:
        return _gate(name, target, None, NOT_MEASURED, "LLM kullanan bölüm koşulmadı")
    value = ", ".join(f"{n} {e['median_seconds_per_file']} sn" for n, e in evidence)
    suspect = [n for n, e in evidence if not e["plausible"]]
    note = f"şüpheli: {', '.join(suspect)}" if suspect else ""
    return _gate(name, target, value, FAIL if suspect else PASS, note)


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


def _header(card: dict) -> str:
    cfg, git = card["config"], card["config"].get("git") or {}
    llm_cfg = cfg.get("llm_settings") or {}
    dirty = git.get("uncommitted_paths")
    lines = [
        f"# Fable skor kartı — {card['run_id']}", "",
        f"- Zaman: {card['started_at']} → {card['finished_at']}",
        f"- Kod: {git.get('branch') or '?'} @ {(git.get('commit') or '?')[:10]}"
        + (f" (+{dirty} commit edilmemiş yol)" if dirty else ""),
        f"- app/ kaynak parmak izi: `{(cfg.get('app_source_sha256') or '?')[:16]}`",
        f"- LLM denetçisi: **{cfg['llm']}** (auditor_provider={llm_cfg.get('auditor_provider')}, "
        f"require_llm_auditor={llm_cfg.get('require_llm_auditor')}, "
        f"model={llm_cfg.get('auditor_model') or '—'})",
        f"- Bölümler: {', '.join(cfg['sections'])} · limit: {cfg['limit'] or 'yok'} · "
        f"gerçek belge: {cfg['real']}",
        f"- Korpus: `{cfg['corpus']}`",
    ]
    if not card["complete"]:
        lines += ["", "> **KISMİ KOŞU** — `--limit`, hatalı ya da eksik bölüm var; bu sayılar "
                      "tam koşularla karşılaştırılamaz."]
    return "\n".join(lines)


def _gates_md(gates: list[dict]) -> str:
    rows = [[g["gate"], g["target"], _num(g["value"]), g["verdict"], g["note"]] for g in gates]
    return "## Kapılar (plan §3)\n\n" + _table(["Kapı", "Hedef", "Değer", "Sonuç", "Not"], rows)


def _gold_rows(full: dict, sub: dict) -> list[list]:
    def both(key, fmt=_num):
        return [fmt(full[key]), fmt(sub[key])]

    by_fmt = " · ".join(f"{k} {fmt_frac(v)}" for k, v in full["critical_recall_by_format"].items())
    return [
        ["Kritik recall (mention × format)", *both("critical_recall", fmt_frac), "pipeline"],
        ["Kritik recall, format başına (60 belge)", by_fmt, "", "pipeline"],
        ["Mention recall", *both("mention_recall"), "pipeline"],
        ["Entity recall", *both("entity_recall"), "pipeline"],
        ["Karakter recall", *both("char_recall"), "detect"],
        ["Karakter precision (yaklaşık)", *both("char_precision_approx"), "detect"],
        ["F2", *both("f2"), "detect"],
        ["Kısmi sızıntı (mention)", *both("partial_leaks"), "pipeline"],
        ["Export'ta sızıntı", *both("leaked_in_export"), "pipeline export"],
        ["NO_MASK ihlali (kirli, alıntılamayın)", *both("no_mask_violations", fmt_frac),
         "pipeline + varsayılan allow-list"],
        ["Belge / kayıt / işlenen",
         *[f"{b['documents']} / {b['records']} / {b['processed']}" for b in (full, sub)], ""],
        ["Durumlar", _counts(full["status_counts"]), _counts(sub["status_counts"]), ""],
        ["Medyan sn/dosya", *both("median_seconds_per_file"), ""],
    ]


def _gold_md(g: dict | None) -> str:
    title = "## (a) Fable GoldBench skorlayıcısı — holdout (pdf + docx + xlsx)"
    if not g:
        return ""
    if g["status"] != "ok":
        return _not_ok(title, g)
    full, sub = g["full"], g["subset20"]
    notes = [
        f"- 20 belgelik alt küme: {sub['rule']}. Bugünkü sıra bu kurala uyuyor: "
        f"{'evet' if sub['rule_matches_holdout_order'] else 'HAYIR'}.",
        "- **detect**: `engine.detect()` orijinal metinde (yayılım, tablo geçişi, allow-list yok). "
        "**pipeline**: değer `run_pipeline` çıktısında yok; pipeline varsayılan 87 terimlik "
        "allow-list'i ekler.",
        "- NO_MASK satırı allow-list ile ölçülür ve liste 8 must_keep teriminin hepsini içerir. "
        "Dürüst aşırı maskeleme sayısı (b) bölümündeki must_keep satırıdır.",
    ]
    if g.get("llm_evidence"):
        ev = g["llm_evidence"]
        notes.append(f"- LLM kanıtı: medyan {ev['median_seconds_per_file']} sn/dosya "
                     f"({'makul' if ev['plausible'] else 'ŞÜPHELİ'}; {ev['expected']}).")
    table = _table(["Ölçüm", "60 belge", "v5 alt kümesi (20)", "Ölçüm yolu"],
                   _gold_rows(full, sub))
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
    title = "## (c) Stres — 72 sabit dosya, tam pipeline"
    if not s:
        return ""
    if s["status"] != "ok":
        return _not_ok(title, s)
    rows = [
        ["Onaylı çıktıya sızıntı, kritik yanlış onay (düşük iyi)", fmt_frac(s["leaks_approved"])],
        ["Herhangi bir durumda sızıntı", fmt_frac(s["leaked_any_status"])],
        ["Güvenli teslim: safe_output → onaylı, sızıntısız", fmt_frac(s["safe_delivery"])],
        ["Fail-closed uyumu", fmt_frac(s["fail_closed_respected"])],
        ["İnsana yönlendirilen (temkinli)", s["routed_to_review"]],
        ["Gerçekten test edilen ve geçen", fmt_frac(s["actually_tested_pass"])],
        ["Durumlar", _counts(s["status_counts"])],
        ["Medyan sn/dosya (pipeline'a giren)", _num(s["median_seconds_per_file"])],
    ]
    ev = s.get("llm_evidence")
    note = f"LLM: **{s['llm']}**" + (
        f" · kanıt: {'makul' if ev['plausible'] else 'ŞÜPHELİ'} ({ev['expected']})" if ev else "")
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
- (a) ve (c) mevcut koşucuları (`run_gold`, `run_stress`) aynen kullanır; `--llm on` =
  `auditor_provider=ollama` + `require_llm_auditor=True`, model yoksa koşu başlamadan durur."""


def render_markdown(card: dict) -> str:
    s = card["sections"]
    parts = [_header(card), _gates_md(card["gates"]), _gold_md(s.get("gold")),
             _strict_md(s.get("strict")), _stress_md(s.get("stress")), _real_md(s.get("real")),
             _timing_md(s), NOTES]
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"
