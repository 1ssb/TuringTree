import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * shareHtml — turn a conversation into a single, self-contained HTML page.
 *
 * The output has its own inline styles and no external assets, so it opens
 * cleanly in any browser and can be dropped into SharePoint / OneDrive / Drive
 * to mint a link anyone can open. Assistant Markdown is rendered to semantic
 * HTML (reusing react-markdown); user text is escaped. No raw HTML from the
 * model is emitted, so the page is safe to share.
 */

export interface ShareSource {
  file: string;
  at: string;
}

export interface ShareMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ShareSource[];
}

export interface ShareMeta {
  docCount?: number;
  folderName?: string;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c] as string,
  );
}

function markdownToHtml(md: string): string {
  return renderToStaticMarkup(
    createElement(ReactMarkdown, { remarkPlugins: [remarkGfm] }, md),
  );
}

const MARK = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <defs><linearGradient id="rgmark" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
    <stop stop-color="#6366f1"/><stop offset="0.5" stop-color="#a855f7"/><stop offset="1" stop-color="#fcd34d"/>
  </linearGradient></defs>
  <path d="M12 22v-9" stroke="#e7e3ff" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M12 13c0-2.4-2-3.4-3.2-4.2M12 13c0-2.4 2-3.4 3.2-4.2" stroke="#e7e3ff" stroke-width="1.4" stroke-linecap="round"/>
  <circle cx="12" cy="22" r="1.5" fill="#e7e3ff"/>
  <circle cx="7" cy="7" r="3.1" fill="url(#rgmark)"/>
  <circle cx="17" cy="7" r="3.1" fill="url(#rgmark)"/>
  <circle cx="12" cy="3.4" r="3.1" fill="url(#rgmark)"/>
</svg>`;

const STYLE = `
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f5f5f7; color: #1b1b21;
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased; }
.sheet { max-width: 760px; margin: 0 auto; background: #fff; min-height: 100vh;
  box-shadow: 0 1px 60px -20px rgba(20,16,40,.25); }
.brandbar { display: flex; align-items: center; gap: 10px; padding: 16px 28px;
  background: #0b0716; color: #f4f1ea; }
.brandbar .name { font-weight: 600; letter-spacing: -.01em; }
.brandbar .tag { margin-left: auto; font-size: 12px; color: #b9b3c9;
  text-transform: uppercase; letter-spacing: .14em; }
.head { padding: 30px 28px 10px; }
.title { margin: 0; font-size: 27px; font-weight: 650; letter-spacing: -.02em; }
.meta { margin: 8px 0 0; font-size: 13px; color: #8a8794; }
.rule { height: 3px; margin: 18px 28px 0; border-radius: 3px;
  background: linear-gradient(90deg, #6366f1, #a855f7, #fcd34d); opacity: .9; }
.convo { padding: 22px 28px 8px; }
.turn { margin: 0 0 26px; }
.role { display: flex; align-items: center; gap: 7px; font-size: 12.5px;
  font-weight: 600; color: #6c6878; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }
.turn.user .bubble { white-space: pre-wrap; background: #f0eefc; border: 1px solid #e7e3f7;
  border-radius: 14px; padding: 12px 15px; font-size: 15px; color: #211d33; }
.md { font-size: 15.5px; color: #26242e; }
.md p { margin: 0 0 12px; } .md p:last-child { margin-bottom: 0; }
.md strong { font-weight: 650; color: #15131c; }
.md ul, .md ol { margin: 0 0 12px; padding-left: 22px; } .md li { margin: 4px 0; }
.md h1,.md h2,.md h3 { line-height: 1.3; margin: 18px 0 8px; }
.md h1 { font-size: 20px; } .md h2 { font-size: 18px; } .md h3 { font-size: 16px; }
.md a { color: #7c3aed; text-decoration: underline; text-underline-offset: 2px; }
.md code { background: #f2f1f5; border-radius: 5px; padding: 1px 6px;
  font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
.md pre { background: #14121c; color: #ece9f5; border-radius: 12px; padding: 14px 16px;
  overflow-x: auto; } .md pre code { background: none; padding: 0; color: inherit; }
.md blockquote { margin: 12px 0; padding: 2px 0 2px 14px; border-left: 3px solid #e3def3; color: #6c6878; }
.md table { border-collapse: collapse; width: 100%; font-size: 14px; margin: 12px 0; }
.md th, .md td { border: 1px solid #ececf1; padding: 7px 10px; text-align: left; }
.md th { background: #faf9fc; }
.sources { margin-top: 12px; }
.sources-label { font-size: 11px; text-transform: uppercase; letter-spacing: .14em; color: #9a96a6; margin-bottom: 7px; }
.chip { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px;
  background: #f7f6fb; border: 1px solid #ecebf2; border-radius: 999px; padding: 4px 11px; margin: 0 6px 6px 0; color: #3b3850; }
.chip em { color: #b06a18; font-style: normal; }
.foot { padding: 22px 28px 36px; color: #9a96a6; font-size: 12.5px; border-top: 1px solid #f0eff3; margin-top: 14px; }
.foot b { color: #6c6878; }
`;

export function buildShareHtml(
  title: string,
  messages: ShareMessage[],
  meta: ShareMeta = {},
): string {
  const turns = messages
    .map((m) => {
      if (m.role === "user") {
        return `<div class="turn user"><div class="role">You</div><div class="bubble">${escapeHtml(
          m.content,
        )}</div></div>`;
      }
      const sources =
        m.sources && m.sources.length
          ? `<div class="sources"><div class="sources-label">Grounded in</div>${m.sources
              .map(
                (s) =>
                  `<span class="chip">${escapeHtml(s.file)}${
                    s.at ? ` <em>${escapeHtml(s.at)}</em>` : ""
                  }</span>`,
              )
              .join("")}</div>`
          : "";
      return `<div class="turn assistant"><div class="role">${MARK} Turing Tree</div><div class="md">${markdownToHtml(
        m.content,
      )}</div>${sources}</div>`;
    })
    .join("\n");

  const docs = meta.docCount
    ? `${meta.docCount.toLocaleString()} document${meta.docCount === 1 ? "" : "s"} · `
    : "";
  const safeTitle = escapeHtml(title || "Turing Tree conversation");
  const date = new Date().toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${safeTitle} — Turing Tree</title>
<style>${STYLE}</style>
</head>
<body>
<div class="sheet">
  <div class="brandbar">${MARK}<span class="name">Turing Tree</span><span class="tag">Shared conversation</span></div>
  <div class="head">
    <h1 class="title">${safeTitle}</h1>
    <p class="meta">${docs}${escapeHtml(date)}</p>
  </div>
  <div class="rule"></div>
  <main class="convo">
${turns}
  </main>
  <footer class="foot">Generated with <b>Turing Tree</b> — a vectorless, reasoning-based RAG that runs fully on your machine. Nothing left the device.</footer>
</div>
</body>
</html>`;
}
