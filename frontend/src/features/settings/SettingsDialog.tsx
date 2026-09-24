import { useEffect, useId, useState, type ReactNode } from "react";
import type { AppSettings, Mode, ProviderId } from "../../api/contract";
import { ApiError } from "../../api/client";
import { useProviders, useSaveSettings, useSettings } from "../../api/queries";
import { errorMessage, modeText, tr } from "../../copy/tr";
import { useTheme, type ThemePreference } from "../../app/theme";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Dialog } from "../../ui/Dialog";
import { Icon } from "../../ui/Icon";
import { Segmented } from "../../ui/Segmented";
import { SkeletonText } from "../../ui/Skeleton";
import { useToast } from "../../ui/Toast";
import { ProviderCard } from "./ProviderCard";
import { TermLists } from "./TermLists";
import s from "./Settings.module.css";

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className={s.section} aria-labelledby={id}>
      <div className={s.sectionHead}>
        <h3 id={id} className={s.sectionTitle}>
          {title}
        </h3>
        {hint ? <p className={s.hint}>{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

const MODES: Mode[] = ["mapping", "destructive"];

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const settings = useSettings();
  const providers = useProviders(open);
  const save = useSaveSettings();
  const toast = useToast();
  const { preference, setPreference } = useTheme();
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const providerId = useId();

  useEffect(() => {
    if (open && settings.data) setDraft(settings.data);
  }, [open, settings.data]);

  const submit = async () => {
    if (!draft) return;
    try {
      await save.mutateAsync(draft);
      onClose();
      toast.show(tr.settings.saved);
    } catch (error) {
      toast.show({ message: errorMessage(error instanceof ApiError ? error.code : "unknown_error"), tone: "error" });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={tr.settings.title}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            {tr.common.cancel}
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={!draft} onClick={() => void submit()}>
            {tr.settings.save}
          </Button>
        </>
      }
    >
      {!draft ? (
        settings.isError ? <p role="alert">{tr.settings.loadError}</p> : <SkeletonText lines={6} />
      ) : (
        <>
          <Section title={tr.settings.modeTitle} hint={tr.settings.modeHint}>
            <div className={s.modes} role="radiogroup" aria-label={tr.settings.modeTitle}>
              {MODES.map((mode) => (
                <label key={mode} className={cx(s.mode, draft.default_mode === mode && s.modeOn)}>
                  <input
                    type="radio"
                    name="default-mode"
                    value={mode}
                    checked={draft.default_mode === mode}
                    onChange={() => setDraft({ ...draft, default_mode: mode })}
                  />
                  <span className={s.modeText}>
                    <span className={s.modeLabel}>
                      <Icon name={mode === "destructive" ? "lock" : "key"} size={14} />
                      {modeText[mode].label}
                    </span>
                    <span className={s.modeConsequence}>{modeText[mode].consequence}</span>
                  </span>
                </label>
              ))}
            </div>
          </Section>

          <Section title={tr.settings.chatTitle}>
            <div className={s.field}>
              <label htmlFor={providerId} className={s.fieldLabel}>
                {tr.settings.defaultProvider}
              </label>
              <select
                id={providerId}
                className={s.select}
                value={draft.chat_default_provider}
                onChange={(event) => setDraft({ ...draft, chat_default_provider: event.target.value as ProviderId })}
              >
                {(providers.data?.providers ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <h4 className={s.subTitle}>{tr.settings.providersTitle}</h4>
            <div className={s.cards}>
              {providers.isPending ? <SkeletonText lines={3} /> : null}
              {(providers.data?.providers ?? []).map((provider) => (
                <ProviderCard key={provider.id} provider={provider} />
              ))}
            </div>
          </Section>

          <Section title={tr.settings.termsTitle} hint={tr.settings.termsHint}>
            <TermLists
              always={draft.always_mask}
              never={draft.never_mask}
              onChange={(always_mask, never_mask) => setDraft({ ...draft, always_mask, never_mask })}
            />
          </Section>

          <Section title={tr.settings.themeTitle}>
            <Segmented<ThemePreference>
              label={tr.settings.themeLabel}
              value={preference}
              onChange={setPreference}
              options={[
                { value: "system", label: tr.settings.theme.system, icon: "monitor" },
                { value: "light", label: tr.settings.theme.light, icon: "sun" },
                { value: "dark", label: tr.settings.theme.dark, icon: "moon" },
              ]}
            />
          </Section>
        </>
      )}
    </Dialog>
  );
}
