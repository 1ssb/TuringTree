import { Download, ExternalLink, X } from "lucide-react";

/**
 * ShareDialog — turn a conversation into a clean, self-contained page you can
 * preview, download, and drop into SharePoint / OneDrive / Drive for a link.
 */
export function ShareDialog({
  html,
  title,
  onClose,
}: {
  html: string;
  title: string;
  onClose: () => void;
}) {
  const fileName = `${(title || "ragindex-conversation")
    .replace(/[^\w-]+/g, "-")
    .slice(0, 40)}.html`;

  const makeUrl = () => URL.createObjectURL(new Blob([html], { type: "text/html" }));

  const download = () => {
    const url = makeUrl();
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  const preview = () => {
    window.open(makeUrl(), "_blank", "noopener");
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-background/70 backdrop-blur-sm"
      />
      <div className="relative w-full max-w-md animate-fade-up-sm rounded-2xl border border-line/15 bg-surface-1 p-5 shadow-[0_40px_120px_-30px_rgba(0,0,0,0.85)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-medium text-foreground">
              Share this conversation
            </h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
              A clean, self-contained page of this chat — it opens in any browser,
              with nothing phoning home.
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

        <div className="mt-4 flex gap-2.5">
          <button
            onClick={preview}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-line/15 bg-surface-2/50 px-3 py-2.5 text-[13px] font-medium text-foreground/90 transition-colors hover:border-line/30 hover:bg-surface-2"
          >
            <ExternalLink className="h-4 w-4" />
            Open preview
          </button>
          <button
            onClick={download}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-foreground px-3 py-2.5 text-[13px] font-medium text-background transition-opacity hover:opacity-90"
          >
            <Download className="h-4 w-4" />
            Download page
          </button>
        </div>

        <div className="mt-4 rounded-xl border border-line/12 bg-surface-2/30 p-3.5">
          <p className="text-[12px] font-medium text-foreground/85">
            Make it a shareable link
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Drop the downloaded{" "}
            <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[11px]">
              .html
            </code>{" "}
            file into <span className="text-foreground/80">SharePoint</span>,
            OneDrive, or Drive and use its <em>Share</em> link — anyone can open it,
            no app needed.
          </p>
        </div>
      </div>
    </div>
  );
}
