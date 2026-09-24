import type { ProviderId, ProviderStatus } from "../../api/contract";
import { errorMessage, providerWhere, tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { CopyText } from "../../ui/CopyText";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import s from "./Chat.module.css";

interface ProviderPickerProps {
  providers: ProviderStatus[];
  value: ProviderId;
  onChange: (id: ProviderId) => void;
}

/** Where the question goes. Unavailable providers say why; login commands are shown, never run. */
export function ProviderPicker({ providers, value, onChange }: ProviderPickerProps) {
  return (
    <fieldset className={s.providers}>
      <legend className={s.legend}>{tr.chat.providerLabel}</legend>
      {providers.map((provider) => {
        const id = `provider-${provider.id}`;
        const checked = provider.id === value;
        return (
          <div key={provider.id} className={cx(s.provider, checked && s.providerChecked, !provider.available && s.providerOff)}>
            <input
              type="radio"
              id={id}
              name="chat-provider"
              value={provider.id}
              checked={checked}
              disabled={!provider.available}
              aria-describedby={`${id}-where`}
              onChange={() => onChange(provider.id)}
            />
            <label htmlFor={id} className={s.providerLabel}>
              <span className={s.providerName}>
                <Icon name={provider.local ? "computer" : "cloud"} size={15} />
                {provider.label}
                {provider.local ? <Badge tone="ok">{tr.settings.provider.local}</Badge> : null}
              </span>
            </label>
            <span id={`${id}-where`} className={s.providerWhere}>
              {provider.available ? providerWhere[provider.id] : errorMessage(provider.problem ?? "provider_unavailable")}
            </span>
            {!provider.available && provider.login_command ? (
              <CopyText text={provider.login_command} className={s.providerCopy} />
            ) : null}
          </div>
        );
      })}
    </fieldset>
  );
}

/** One-line summary once a conversation is under way; the full list is a click away. */
export function ProviderSummary({ provider, onChange }: { provider: ProviderStatus; onChange: () => void }) {
  return (
    <div className={s.summary}>
      <span className={s.legend}>{tr.chat.providerLabel}</span>
      <div className={s.summaryRow}>
        <span className={s.summaryIcon} aria-hidden="true">
          <Icon name={provider.local ? "computer" : "cloud"} size={15} />
        </span>
        <span className={s.summaryText}>
          <span className={s.providerName}>{provider.label}</span>
          <span className={s.providerWhere}>{providerWhere[provider.id]}</span>
        </span>
        <Button size="sm" variant="link" aria-label={tr.chat.changeProviderLabel} onClick={onChange}>
          {tr.chat.changeProvider}
        </Button>
      </div>
    </div>
  );
}
