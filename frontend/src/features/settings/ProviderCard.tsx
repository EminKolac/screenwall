import type { ProviderStatus } from "../../api/contract";
import { errorMessage, tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { CopyText } from "../../ui/CopyText";
import { Icon } from "../../ui/Icon";
import s from "./Settings.module.css";

function Fact({ ok, yes, no }: { ok: boolean | null; yes: string; no: string }) {
  if (ok === null) return null;
  return (
    <li className={ok ? s.factOk : s.factNo}>
      <Icon name={ok ? "check" : "x"} size={13} />
      {ok ? yes : no}
    </li>
  );
}

/** Installation, compatibility and login state of one chat provider. */
export function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const p = tr.settings.provider;
  return (
    <article className={s.card} aria-labelledby={`provider-card-${provider.id}`}>
      <header className={s.cardHead}>
        <Icon name={provider.local ? "computer" : "cloud"} size={16} />
        <h4 id={`provider-card-${provider.id}`} className={s.cardTitle}>
          {provider.label}
        </h4>
        <Badge tone={provider.available ? "ok" : "warn"} icon={provider.available ? "check" : "alert"}>
          {provider.available ? p.ready : p.notReady}
        </Badge>
      </header>
      <ul className={s.facts}>
        <li className={s.factPlain}>{provider.local ? p.local : p.cloud}</li>
        <Fact ok={provider.installed} yes={p.installed} no={p.notInstalled} />
        <Fact ok={provider.compatible} yes={p.compatible} no={p.incompatible} />
        <Fact ok={provider.authenticated} yes={p.loggedIn} no={p.loggedOut} />
        {provider.version ? <li className={s.factPlain}>{p.version(provider.version)}</li> : null}
        {provider.model ? <li className={s.factPlain}>{p.model(provider.model)}</li> : null}
      </ul>
      {!provider.available && provider.problem ? <p className={s.problem}>{errorMessage(provider.problem)}</p> : null}
      {provider.login_command && provider.authenticated === false ? (
        <div className={s.login}>
          <span className={s.loginLabel}>{tr.chat.loginCommand}</span>
          <CopyText text={provider.login_command} />
        </div>
      ) : null}
    </article>
  );
}
