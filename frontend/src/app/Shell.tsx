import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { tr } from "../copy/tr";
import { LibraryPane } from "../features/library/LibraryPane";
import { UploadDropzone } from "../features/library/UploadDropzone";
import { UploadProvider, useUploads } from "../features/library/uploadContext";
import { SettingsDialog } from "../features/settings/SettingsDialog";
import { BrandMark } from "../ui/BrandMark";
import { IconButton } from "../ui/IconButton";
import { COMPACT_QUERY, useMediaQuery } from "../ui/useMediaQuery";
import { Drawer } from "./Drawer";
import { ErrorBoundary } from "./ErrorBoundary";
import { ShellContext } from "./shellContext";
import s from "./Shell.module.css";

function TopBar({ onMenu, onSettings }: { onMenu: () => void; onSettings: () => void }) {
  const { pick } = useUploads();
  return (
    <header className={s.topbar}>
      <IconButton icon="menu" label={tr.app.openLibrary} aria-haspopup="dialog" onClick={onMenu} />
      <span className={s.brand}>
        <BrandMark />
        {tr.app.name}
      </span>
      <span className={s.spacer} />
      <IconButton icon="upload" label={tr.library.upload} onClick={pick} />
      <IconButton icon="settings" label={tr.app.settings} onClick={onSettings} />
    </header>
  );
}

export function Shell() {
  const compact = useMediaQuery(COMPACT_QUERY);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setDrawerOpen(false), [location.pathname, compact]);

  const shell = useMemo(
    () => ({ openSettings: () => setSettingsOpen(true), openLibrary: () => setDrawerOpen(true), compact }),
    [compact],
  );

  const openSettingsFromLibrary = () => {
    setDrawerOpen(false);
    setSettingsOpen(true);
  };

  return (
    <ShellContext.Provider value={shell}>
      <UploadProvider>
        <a
          className="skip-link"
          href="#main"
          onClick={(event) => {
            event.preventDefault();
            document.getElementById("main")?.focus();
          }}
        >
          {tr.app.skipLink}
        </a>
        <div className={s.shell}>
          {compact ? (
            <TopBar onMenu={() => setDrawerOpen(true)} onSettings={() => setSettingsOpen(true)} />
          ) : (
            <aside className={s.library} aria-label={tr.library.title}>
              <LibraryPane onOpenSettings={openSettingsFromLibrary} />
            </aside>
          )}
          <main id="main" className={s.main} tabIndex={-1}>
            <ErrorBoundary key={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
        {compact ? (
          <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} label={tr.library.title}>
            <LibraryPane onOpenSettings={openSettingsFromLibrary} onClose={() => setDrawerOpen(false)} />
          </Drawer>
        ) : null}
        <UploadDropzone />
        <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </UploadProvider>
    </ShellContext.Provider>
  );
}
