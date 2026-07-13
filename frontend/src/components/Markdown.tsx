import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown — renders an assistant message's Markdown into clean, themed elements.
 *
 * The local model answers in Markdown (bold, lists, headings, code, tables…), so
 * we parse it rather than printing the raw `**…**`. Every element is mapped to a
 * small, on-brand style; raw HTML is intentionally NOT enabled, so model output
 * can never inject markup.
 */

const components: Components = {
  p: ({ children }) => <p className="mb-3 leading-[1.75] last:mb-0">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-accent underline decoration-accent/40 underline-offset-2 transition-colors hover:decoration-accent"
    >
      {children}
    </a>
  ),
  ul: ({ children }) => (
    <ul className="mb-3 ml-5 list-disc space-y-1.5 last:mb-0 marker:text-muted/60">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3 ml-5 list-decimal space-y-1.5 last:mb-0 marker:text-muted/60">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1 leading-[1.7]">{children}</li>,
  h1: ({ children }) => (
    <h1 className="mb-3 mt-5 font-display text-xl font-semibold first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2.5 mt-5 font-display text-lg font-semibold first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-[15px] font-semibold text-foreground first:mt-0">
      {children}
    </h3>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-line/30 pl-3.5 text-muted">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-line/15" />,
  code: ({ className, children }) => {
    const text = String(children ?? "");
    const isBlock = text.includes("\n") || /language-/.test(className ?? "");
    if (isBlock) {
      return (
        <code className="font-mono text-[13px] leading-relaxed">{children}</code>
      );
    }
    return (
      <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[12.5px] text-foreground/90">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="thin-scroll my-3 overflow-x-auto rounded-xl border border-line/12 bg-surface-1 p-3.5 last:mb-0">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="thin-scroll my-3 overflow-x-auto rounded-xl border border-line/12">
      <table className="w-full border-collapse text-[13.5px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-line/20 bg-surface-1 text-left text-muted">
      {children}
    </thead>
  ),
  th: ({ children }) => <th className="px-3 py-2 font-medium">{children}</th>,
  td: ({ children }) => (
    <td className="border-t border-line/10 px-3 py-2 align-top">{children}</td>
  ),
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-[15px] text-foreground/90">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
