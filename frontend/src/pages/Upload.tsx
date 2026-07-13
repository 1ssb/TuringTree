import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FolderUp, FileUp, ArrowRight, Check, Lock, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/brand";
import Lightfall from "@/components/ui/Lightfall";
import { buildIndexWithProgress, type BuildProgress } from "@/lib/api";

/**
 * Upload — "Index a folder."
 * --------------------------
 * A Lightfall field sits behind a translucent, dashed-border drop box that
 * spans from just below the wordmark to the bottom of the screen. The overlay
 * is kept light by default and darkens while a file is being dropped (a small
 * UX cue), and the upload glyph animates during the drop.
 */

interface PickedFile {
  name: string;
  size: number;
}

const FORMATS = "PDF · Markdown · TXT · DOCX · HTML";

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}

/** Human-friendly duration, e.g. 45 -> "45s", 95 -> "1m 35s". */
function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}

function plural(n: number, one: string, many = `${one}s`) {
  return n === 1 ? one : many;
}

/** Animated upload glyph — a tray with a gradient arrow that bobs while active. */
function UploadGlyph({ active }: { active: boolean }) {
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 48 48"
      fill="none"
      className="h-16 w-16"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id="uploadGrad"
          x1="8"
          y1="8"
          x2="40"
          y2="40"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#6366f1" />
          <stop offset="0.5" stopColor="#a855f7" />
          <stop offset="1" stopColor="#fcd34d" />
        </linearGradient>
      </defs>
      {/* tray */}
      <path
        d="M12 30v4a4 4 0 0 0 4 4h16a4 4 0 0 0 4-4v-4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        className="text-foreground/70"
      />
      {/* arrow (bobs while a file is being dropped) */}
      <g className={active ? "animate-upload-bob" : ""}>
        <path
          d="M24 32V13"
          stroke="url(#uploadGrad)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M15.5 21 24 12.5 32.5 21"
          stroke="url(#uploadGrad)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}

/** A small rounded stat chip used on the upload summary. */
function StatPill({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-line/15 bg-white/[0.03] px-3.5 py-1.5 text-[13px] text-foreground/80">
      {label}
    </span>
  );
}

/**
 * Recursively collect File objects from a dropped FileSystemEntry (a folder or a
 * file), tagging each with its folder-relative path so the index keeps structure.
 * Dropped FOLDERS are NOT present in dataTransfer.files — they exist only behind
 * webkitGetAsEntry — which is why a plain dataTransfer.files read drops them.
 */
async function readEntryFiles(entry: FileSystemEntry, out: File[]): Promise<void> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry;
    const file = await new Promise<File>((resolve, reject) =>
      fileEntry.file(resolve, reject),
    );
    try {
      Object.defineProperty(file, "webkitRelativePath", {
        value: String(entry.fullPath || file.name).replace(/^\/+/, ""),
        configurable: true,
      });
    } catch {
      /* webkitRelativePath is read-only in some engines — the name still works */
    }
    out.push(file);
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const readBatch = () =>
      new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      );
    // readEntries returns at most ~100 entries per call, so loop until empty.
    for (let batch = await readBatch(); batch.length; batch = await readBatch()) {
      for (const child of batch) await readEntryFiles(child, out);
    }
  }
}

export default function Upload() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [showToast, setShowToast] = useState(false);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [progress, setProgress] = useState<BuildProgress | null>(null);
  // Wall-clock anchor of the last server poll, so the bar/ETA can advance
  // smoothly between the ~1s polls instead of stepping.
  const progressAt = useRef<number>(0);
  // Frozen total-time estimate (seconds), captured on the first poll, so the bar
  // curve has a stable time constant and never jumps around.
  const estimateRef = useRef<number>(0);
  const [, setTick] = useState(0); // forces a re-render ~5x/sec while building

  // The real File objects (not just display metadata) so we can upload them.
  const rawFiles = useRef<File[]>([]);

  const addFiles = (raw: File[]) => {
    if (!raw.length) return;
    rawFiles.current = raw;
    setFiles(
      raw.map((f) => ({
        name:
          (f as File & { webkitRelativePath?: string }).webkitRelativePath ||
          f.name,
        size: f.size,
      })),
    );
    setBuildError(null);
    setShowToast(true);
    window.setTimeout(() => setShowToast(false), 2800);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    // Capture folder entries SYNCHRONOUSLY — the DataTransfer is only valid during
    // the event, and a dropped folder's files live behind webkitGetAsEntry, not in
    // dataTransfer.files. Then read them (recursively) asynchronously.
    const entries = Array.from(e.dataTransfer.items || [])
      .map((item) => item.webkitGetAsEntry?.() ?? null)
      .filter((entry): entry is FileSystemEntry => entry !== null);
    const flatFiles = Array.from(e.dataTransfer.files);
    if (!entries.length) {
      addFiles(flatFiles);
      return;
    }
    void (async () => {
      const collected: File[] = [];
      for (const entry of entries) await readEntryFiles(entry, collected);
      addFiles(collected.length ? collected : flatFiles);
    })();
  };

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(e.target.files ?? []));
  };

  const clearFiles = () => {
    rawFiles.current = [];
    setFiles([]);
    setBuildError(null);
  };

  const folderCount = new Set(
    files.map((f) => (f.name.includes("/") ? f.name.split("/")[0] : null)).filter(Boolean),
  ).size;
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  const fileTypes = new Set(
    files.map((f) => f.name.split(".").pop()?.toLowerCase()).filter(Boolean),
  ).size;
  const hasFiles = files.length > 0;
  const folderName =
    files.find((f) => f.name.includes("/"))?.name.split("/")[0] || "your documents";

  const handleBuild = async () => {
    if (!rawFiles.current.length || building) return;
    setBuilding(true);
    setBuildError(null);
    setProgress(null);
    progressAt.current = Date.now();
    estimateRef.current = 0;
    try {
      const result = await buildIndexWithProgress(
        rawFiles.current,
        (p) => {
          setProgress(p);
          progressAt.current = Date.now();
          // Freeze the total estimate from the first poll for a stable curve.
          if (!estimateRef.current && p.eta != null) {
            estimateRef.current = Math.max(8, p.elapsed + p.eta);
          }
        },
      );
      navigate("/chat", {
        state: {
          fileCount: result.doc_count,
          folderName,
          documents: result.documents,
        },
      });
    } catch (err) {
      setBuilding(false);
      setProgress(null);
      setBuildError(
        err instanceof Error ? err.message : "Could not build the index.",
      );
    }
  };

  // While building, tick a few times a second so the time-based bar advances
  // smoothly between the server's ~1s progress polls.
  useEffect(() => {
    if (!building) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 200);
    return () => window.clearInterval(id);
  }, [building]);

  // Smooth, honest progress. We blend real done/total with a TIME-based estimate
  // shaped as an asymptotic curve (1 - e^(-t/tau)): it rises quickly, then eases
  // off, always creeping upward and NEVER freezing at 99% when the model takes
  // longer than estimated. A live shimmer (below) keeps the bar visibly active.
  const sincePoll = building ? (Date.now() - progressAt.current) / 1000 : 0;
  const liveElapsed = progress ? progress.elapsed + sincePoll : 0;
  const liveEta =
    progress?.eta != null ? Math.max(0, progress.eta - sincePoll) : null;
  const docFraction =
    progress && progress.total > 0 ? progress.done / progress.total : 0;
  const tau = Math.max(8, estimateRef.current || liveElapsed + (liveEta ?? 20));
  const timeFraction = 1 - Math.exp(-liveElapsed / tau);
  const percent = building
    ? Math.min(98, Math.max(3, Math.round(Math.max(docFraction, timeFraction) * 100)))
    : 0;
  // Drop the countdown once the estimate is spent — a number ticking to 0 then
  // sitting there is exactly what reads as "stuck". The shimmer + this label make
  // it clear we're still working through the last stretch.
  const showCountdown =
    liveEta != null && liveEta >= 1 && liveElapsed < tau && percent < 90;
  const etaLabel = showCountdown
    ? `~${formatDuration(liveEta as number)} remaining`
    : "Finishing up…";

  return (
    <div className="relative flex h-screen flex-col overflow-hidden bg-background text-foreground antialiased">
      {/* Lightfall background */}
      <div className="absolute inset-0 z-0">
        <Lightfall
          colors={["#6366f1", "#a855f7", "#c4b5fd"]}
          backgroundColor="#190a3a"
          speed={0.5}
          streakCount={3}
          density={0.6}
          glow={1}
          twinkle={1}
          zoom={3}
          backgroundGlow={0.5}
          mouseInteraction
          mouseStrength={0.5}
          mouseRadius={1}
        />
      </div>

      {/* Overlay — light by default, darkens while dropping a file */}
      <div
        aria-hidden="true"
        className={`absolute inset-0 z-0 transition-colors duration-500 ${isDragging ? "bg-background/70" : "bg-background/35"
          }`}
      />

      {/* Header — brand only */}
      <header className="relative z-10 shrink-0 px-8 py-6">
        <Link to="/" className="inline-block rounded-lg outline-none">
          <Wordmark />
        </Link>
      </header>

      {/* Translucent dashed drop box — spans from below the wordmark to the bottom */}
      <main className="relative z-10 flex flex-1 px-5 pb-5 pt-1">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={`relative flex flex-1 flex-col overflow-hidden rounded-[28px] border-2 border-dashed backdrop-blur-[2px] transition-all duration-300 ${isDragging
            ? "border-accent/60 bg-accent/[0.05]"
            : "border-line/25 bg-white/[0.02]"
            }`}
        >
          {/* soft accent glow inside the box while dropping */}
          {isDragging && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  "radial-gradient(circle at 50% 42%, rgba(167,139,250,0.16), transparent 60%)",
              }}
            />
          )}

          {/* Individual files (PDF / Markdown / TXT / DOCX / HTML). */}
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.md,.markdown,.txt,.text,.docx,.html,.htm"
            className="hidden"
            onChange={handlePick}
          />
          {/* A whole folder (the picker recurses into it). */}
          <input
            ref={folderInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handlePick}
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          />

          {!hasFiles ? (
            /* Idle / drag-active */
            <div className="relative flex flex-1 flex-col items-center justify-center px-6 text-center animate-fade-up">
              <UploadGlyph active={isDragging} />

              <h1 className="mt-7 font-display text-5xl font-medium tracking-tight sm:text-6xl">
                {isDragging ? "Drop to begin" : "Index your documents"}
              </h1>
              <p className="mt-4 max-w-md text-base leading-7 text-muted">
                Drag files or a whole folder anywhere in this box — Turing Tree reads
                each one and grows a reasoning tree, fully on your machine.
              </p>

              <div className="mt-7 flex items-center gap-4">
                <button
                  onClick={() => inputRef.current?.click()}
                  className="group inline-flex items-center gap-2 text-sm font-medium text-foreground/90 transition-colors hover:text-accent"
                >
                  <FileUp className="h-4 w-4" />
                  <span className="underline decoration-line/40 underline-offset-4 transition-colors group-hover:decoration-accent">
                    Browse files
                  </span>
                </button>
                <span className="text-muted/40">or</span>
                <button
                  onClick={() => folderInputRef.current?.click()}
                  className="group inline-flex items-center gap-2 text-sm font-medium text-foreground/90 transition-colors hover:text-accent"
                >
                  <FolderUp className="h-4 w-4" />
                  <span className="underline decoration-line/40 underline-offset-4 transition-colors group-hover:decoration-accent">
                    a whole folder
                  </span>
                </button>
              </div>

              <p className="mt-10 text-[11px] uppercase tracking-[0.18em] text-muted/60">
                {FORMATS}
              </p>
            </div>
          ) : building ? (
            /* Processing */
            <div className="relative flex flex-1 flex-col items-center justify-center px-6 text-center animate-fade-up">
              <UploadGlyph active />

              {/* Make the hand-off obvious: the files are in, we're now indexing. */}
              <div className="mt-6 flex items-center gap-2.5 text-[12px] font-medium">
                <span className="inline-flex items-center gap-1.5 text-foreground/70">
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  Uploaded
                </span>
                <ArrowRight className="h-3.5 w-3.5 text-muted/50" />
                <span className="inline-flex items-center gap-1.5 text-accent">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  Indexing
                </span>
              </div>

              <h1 className="mt-4 font-display text-4xl font-medium tracking-tight sm:text-5xl">
                Indexing your documents…
              </h1>
              <p className="mt-4 max-w-md text-base leading-7 text-foreground/70">
                Your {files.length.toLocaleString()}{" "}
                {plural(files.length, "file")} {plural(files.length, "is", "are")} in —
                now growing a reasoning tree with the local model. This runs entirely
                on your machine, so it can take a moment.
              </p>
              <div className="mt-8 w-72 max-w-full">
                <div className="relative h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-[#6366f1] via-[#a855f7] to-[#fcd34d] transition-[width] duration-500 ease-out"
                    style={{ width: `${percent}%` }}
                  />
                  {/* Continuous shimmer so the bar always reads as ACTIVE, even
                      while the model finishes the last stretch (no frozen look). */}
                  <div className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-indeterminate bg-gradient-to-r from-transparent via-white/30 to-transparent" />
                </div>
                <div className="mt-2.5 flex items-center justify-between text-[12px] tabular-nums text-muted">
                  <span>{percent}%</span>
                  <span>{etaLabel}</span>
                </div>
                {progress && progress.total > 1 && (
                  <p className="mt-1 text-[11px] text-muted/70">
                    {progress.done} / {progress.total} documents indexed
                  </p>
                )}
              </div>
              {buildError && (
                <p className="mt-5 text-[12px] text-[#e3866b]">{buildError}</p>
              )}
            </div>
          ) : (
            /* Ready — compact stats (no per-file list) */
            <div className="relative flex flex-1 flex-col items-center justify-center px-6 text-center animate-fade-up">
              <p className="text-xs uppercase tracking-[0.18em] text-accent/80">
                Ready to index
              </p>
              <h1 className="mt-3 font-display text-5xl font-medium tracking-tight sm:text-6xl">
                {files.length.toLocaleString()} {plural(files.length, "file")}
              </h1>

              <div className="mt-7 flex flex-wrap items-center justify-center gap-2.5">
                {folderCount > 0 && (
                  <StatPill
                    label={`${folderCount.toLocaleString()} ${plural(folderCount, "folder")}`}
                  />
                )}
                <StatPill label={formatBytes(totalBytes)} />
                {fileTypes > 0 && (
                  <StatPill label={`${fileTypes} ${plural(fileTypes, "type")}`} />
                )}
              </div>

              <Button
                variant="heroPrimary"
                className="group mt-9 px-7 py-3.5 text-base"
                onClick={handleBuild}
              >
                Build the index
                <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
              </Button>

              <button
                onClick={clearFiles}
                className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
                Choose a different folder
              </button>

              {buildError && (
                <p className="mt-4 text-[12px] text-[#e3866b]">{buildError}</p>
              )}
            </div>
          )}

          {/* Footer note inside the box */}
          <div className="relative flex shrink-0 items-center justify-center gap-1.5 pb-5 text-xs text-muted">
            <Lock className="h-3 w-3" />
            Encrypted · nothing leaves your machine.
          </div>
        </div>
      </main>

      {/* Toast */}
      {showToast && (
        <div className="fixed bottom-7 left-1/2 z-20 flex -translate-x-1/2 animate-toast-in items-center gap-2.5 rounded-full border border-line/15 bg-background/80 px-4 py-2.5 backdrop-blur-md">
          <span className="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-[#6366f1] to-[#a855f7]" />
          <span className="text-[13px] text-foreground/85">
            Folder added — nothing left your machine.
          </span>
        </div>
      )}
    </div>
  );
}
