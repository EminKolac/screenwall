import { useEffect, useRef, useState } from "react";
import { modeText, tr } from "../../copy/tr";
import { Icon } from "../../ui/Icon";
import { useUploads } from "./uploadContext";
import s from "./UploadDropzone.module.css";

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");

/** Drop files anywhere on the window. The keyboard path is the "Yükle" button. */
export function UploadDropzone() {
  const { enqueue, mode } = useUploads();
  const [active, setActive] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setActive(true);
    };
    const over = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setActive(false);
      if (event.dataTransfer?.files.length) enqueue(event.dataTransfer.files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [enqueue]);

  if (!active) return null;
  return (
    <div className={s.overlay} aria-hidden="true">
      <div className={s.card}>
        <span className={s.icon}>
          <Icon name="upload" size={26} />
        </span>
        <p className={s.title}>{tr.upload.dropTitle}</p>
        <p className={s.body}>{tr.upload.dropBody(modeText[mode].label)}</p>
      </div>
    </div>
  );
}
