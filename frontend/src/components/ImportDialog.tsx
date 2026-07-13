import { useRef, useState } from "react";
import { FileUp, X } from "lucide-react";

/**
 * ImportDialog — restore a chat from a RagIndex bundle (paste or file).
 *
 * The parent does the actual parsing + restore via `onImport(text)`; this just
 * collects the bundle (pasted JSON or a chosen .ragindex.json file) and surfaces
 * progress / errors.
 */
export function ImportDialog({
  onClose,
  onImport,
}: {
  onClose: () => void;
  onImport: (text: string) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const run = async (payload: string) => {
    if (!payload.trim()) {
      setError("Paste a bundle or choose a file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onImport(payload);
      onClose();
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : "Import failed.");
    }
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result ?? "");
      setText(content);
      run(content);
    };
    reader.onerror = () => setError("Could not read that file.");
    reader.readAsText(file);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-background/70 backdrop-blur-sm"
      />
      <div className="relative w-full max-w-lg animate-fade-up-sm rounded-2xl border border-line/15 bg-surface-1 p-5 shadow-[0_40px_120px_-30px_rgba(0,0,0,0.85)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-medium text-foreground">
              Resume a chat
            </h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
              Paste a Turing Tree bundle or load a{" "}
              <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[11px]">
                .ragindex.json
              </code>{" "}
              file. It restores the conversation and its index, so you can pick up
              exactly where it left off — fully on this machine.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <X className="h-[18px] w-[18px]" />
          </button>
        </div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the bundle here…"
          spellCheck={false}
          className="thin-scroll mt-4 h-40 w-full resize-none rounded-xl border border-line/15 bg-surface-2/40 p-3 font-mono text-[12px] leading-relaxed text-foreground/90 placeholder:text-muted/50 focus:border-accent/40 focus:outline-none"
        />

        {error && <p className="mt-2 text-[12px] text-[#e3866b]">{error}</p>}

        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            onClick={() => fileRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <FileUp className="h-4 w-4" />
            Choose file
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={onFile}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="rounded-lg px-3.5 py-2 text-[13px] text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => run(text)}
              disabled={busy}
              className="rounded-lg bg-foreground px-4 py-2 text-[13px] font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Restoring…" : "Resume chat"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
