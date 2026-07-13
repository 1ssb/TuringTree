import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowUp,
  ArrowRight,
  ChevronDown,
  Download,
  FolderInput,
  Menu,
  Paperclip,
  Plus,
  RotateCcw,
  Share2,
  Settings,
  Trash2,
  Upload,
  UploadCloud,
  MessageSquare,
} from "lucide-react";

import { BrandMark } from "@/components/brand";
import { ImportDialog } from "@/components/ImportDialog";
import { ShareDialog } from "@/components/ShareDialog";
import { Markdown } from "@/components/Markdown";
import { TreeView } from "@/components/TreeView";
import {
  chat,
  exportStore,
  getIndexStatus,
  importStore,
  resetIndex,
  type ChatConfidence,
  type ConfidenceDrivers,
  type IndexStatus,
} from "@/lib/api";

/**
 * Chat — "Ask your index."
 * ------------------------
 * A focused, ChatGPT-style workspace: a collapsible history sidebar on the left
 * (account on top, past chats in the middle, settings at the bottom) and the
 * conversation on the right. Deliberately restrained — neutral surfaces, the
 * brand gradient reserved for the mark — so the reading stays the focus.
 * Conversations persist locally (localStorage); answers come from the real
 * vectorless backend (/api/chat) grounded in the indexed files.
 */

interface Corpus {
  fileCount?: number;
  folderName?: string;
}

interface Source {
  file: string;
  at: string;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  confidence?: ChatConfidence | null;
  meta?: { sections: number; branches: number };
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
}

// Playful, on-brand lines shown while the local model works. They cycle
// (shuffled per question) so the wait feels alive instead of frozen on one label.
export const THINKING_LINES = [
  "Searching the index…",
  "Reading the matching sections…",
  "Climbing the reasoning tree…",
  "Following the branches that matter…",
  "Weighing the evidence…",
  "Tracing each claim back to its source…",
  "Pruning the unlikely paths…",
  "Connecting dots across your documents…",
  "Thinking locally — no cloud in sight…",
  "Letting the little neurons cook…",
  "Cross-examining the footnotes…",
  "Listening for what the documents agree on…",
];

/** Fisher–Yates shuffle (returns a copy) so each question gets a fresh order. */
export function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const EXAMPLES = [
  "Summarize the key points across these documents",
  "Where is the methodology defined?",
  "What claims still need a citation?",
];

const STORAGE_KEY = "ragindex.chats.v1";

function plural(n: number, one: string, many = `${one}s`) {
  return n === 1 ? one : many;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function newConversation(): Conversation {
  return { id: uid(), title: "New chat", messages: [], createdAt: Date.now() };
}

function deriveTitle(text: string): string {
  const t = text.trim().replace(/\s+/g, " ");
  return t.length > 38 ? `${t.slice(0, 38)}…` : t;
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Conversation[];
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }
  } catch {
    /* ignore corrupt storage */
  }
  return [newConversation()];
}

/** Small gradient dot — the one spot of brand colour in the conversation. */
function GradientDot({ className = "" }: { className?: string }) {
  return (
    <span
      className={`rounded-full bg-gradient-to-r from-[#6366f1] via-[#a855f7] to-[#fcd34d] ${className}`}
    />
  );
}

/**
 * Confidence badge — turns the answer's 0..100 confidence into an at-a-glance,
 * interpretable pill: a coloured dot, the percentage, and a plain-English tier.
 */
const CONF_TONES = {
  high: { dot: "bg-emerald-400", text: "text-emerald-300", border: "border-emerald-400/25" },
  good: { dot: "bg-lime-400", text: "text-lime-300", border: "border-lime-400/25" },
  mixed: { dot: "bg-amber-400", text: "text-amber-300", border: "border-amber-400/25" },
  low: { dot: "bg-rose-400", text: "text-rose-300", border: "border-rose-400/25" },
} as const;

function confidenceTier(score: number): { key: keyof typeof CONF_TONES; label: string } {
  if (score >= 80) return { key: "high", label: "High confidence" };
  if (score >= 65) return { key: "good", label: "Confident" };
  if (score >= 45) return { key: "mixed", label: "Mixed support" };
  return { key: "low", label: "Low confidence" };
}

// The signals behind the score, each a plain-English question the metric answers.
const DRIVER_META: { key: keyof ConfidenceDrivers; label: string; hint: string }[] = [
  { key: "focus", label: "Focus", hint: "Does it land on one clear region of the source?" },
  { key: "cohesion", label: "Cohesion", hint: "Is the supporting evidence compact, not scattered?" },
  { key: "consistency", label: "Consistency", hint: "Do the retrieved pieces agree with each other?" },
];

function driverTone(v: number): string {
  return v >= 65 ? "bg-emerald-400" : v >= 45 ? "bg-amber-400" : "bg-rose-400";
}

function ConfidenceBadge({ c }: { c: ChatConfidence }) {
  const [open, setOpen] = useState(false);
  const pct = Math.max(0, Math.min(100, Math.round(c.score)));
  const tier = confidenceTier(pct);
  const tone = CONF_TONES[tier.key];
  const drivers = c.drivers;
  return (
    <div className="inline-flex flex-col items-start gap-1.5">
      <button
        type="button"
        onClick={() => drivers && setOpen((o) => !o)}
        className={`inline-flex items-center gap-2 rounded-full border ${tone.border} bg-surface-1 px-2.5 py-1 ${drivers ? "cursor-pointer transition-colors hover:bg-surface-2" : "cursor-default"}`}
        title={`Answer confidence ${pct}% (${c.verdict})${c.grounded ? "" : " — offline estimate"}`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
        <span className={`text-[12px] font-semibold tabular-nums ${tone.text}`}>{pct}%</span>
        <span className="text-[12px] text-muted">{tier.label}</span>
        {drivers && (
          <ChevronDown
            className={`h-3 w-3 text-muted transition-transform ${open ? "rotate-180" : ""}`}
          />
        )}
      </button>

      {open && drivers && (
        <div className="w-[260px] max-w-full rounded-xl border border-line/12 bg-surface-1 p-3">
          <div className="space-y-2">
            {DRIVER_META.map(({ key, label, hint }) => {
              const v = Math.max(0, Math.min(100, Math.round(drivers[key])));
              return (
                <div key={key} title={hint}>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-foreground/70">{label}</span>
                    <span className="tabular-nums text-muted">{v}%</span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
                    <div
                      className={`h-full rounded-full ${driverTone(v)}`}
                      style={{ width: `${v}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          {c.reason && (
            <p className="mt-2.5 border-t border-line/10 pt-2 text-[11px] leading-snug text-muted">
              {c.reason}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Reveals an assistant answer progressively — a lightweight "typing" effect that
 * makes the wait feel alive — then settles into the full Markdown render. While
 * typing it shows plain text + a caret (cheap to re-render); the reveal is bounded
 * to ~70 steps so even long answers stay smooth, and it respects
 * prefers-reduced-motion (showing everything at once).
 */
export function TypewriterAnswer({ text, onDone }: { text: string; onDone?: () => void }) {
  const [shown, setShown] = useState("");
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !text) {
      setShown(text);
      doneRef.current?.();
      return;
    }
    const tokens = text.split(/(\s+)/); // words + the whitespace between them
    const perStep = Math.max(1, Math.ceil(tokens.length / 70));
    let i = 0;
    setShown("");
    const id = window.setInterval(() => {
      i = Math.min(tokens.length, i + perStep);
      setShown(tokens.slice(0, i).join(""));
      if (i >= tokens.length) {
        window.clearInterval(id);
        doneRef.current?.();
      }
    }, 30);
    return () => window.clearInterval(id);
  }, [text]);

  if (shown.length >= text.length) return <Markdown>{text}</Markdown>;
  return (
    <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-foreground/90">
      {shown}
      <span
        aria-hidden="true"
        className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] animate-pulse rounded-full bg-accent"
      />
    </p>
  );
}

/**
 * One conversation message. Memoized so typing in the composer (which re-renders
 * Chat on every keystroke) doesn't re-render — or re-parse the Markdown of —
 * every prior message. It depends only on `msg` (+ the transient `animate` flag),
 * so React.memo is a clean win.
 */
const ChatMessage = memo(function ChatMessage({
  msg,
  animate = false,
  onTyped,
}: {
  msg: Message;
  animate?: boolean;
  onTyped?: () => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex animate-fade-up-sm justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-3xl rounded-tr-lg bg-surface-2 px-4 py-3 text-[14.5px] leading-relaxed text-foreground/90">
          {msg.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex animate-fade-up-sm gap-3.5">
      <BrandMark className="mt-0.5 h-7 w-7 shrink-0" />
      <div className="min-w-0 flex-1">
        {msg.confidence && (
          <div className="mb-2">
            <ConfidenceBadge c={msg.confidence} />
          </div>
        )}
        {msg.meta && (
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-muted">
            <span className="flex items-center gap-1.5 text-foreground/75">
              <GradientDot className="h-1.5 w-1.5" />
              read {msg.meta.sections} {plural(msg.meta.sections, "section")}
            </span>
            <span className="text-muted/40">·</span>
            <span>
              over {msg.meta.branches} {plural(msg.meta.branches, "document")}
            </span>
          </div>
        )}

        <div className="mt-2.5">
          {animate ? (
            <TypewriterAnswer text={msg.content} onDone={onTyped} />
          ) : (
            <Markdown>{msg.content}</Markdown>
          )}
        </div>

        {msg.sources && msg.sources.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-[11px] uppercase tracking-[0.16em] text-muted">
              Grounded in
            </p>
            <div className="flex flex-wrap gap-2">
              {msg.sources.map((s) => (
                <span
                  key={`${s.file}-${s.at}`}
                  className="flex items-center gap-2 rounded-full border border-line/12 bg-surface-1 px-3 py-1.5 text-[12px]"
                >
                  <span className="text-foreground/80">{s.file}</span>
                  {s.at && <span className="text-[#e3b26b]">{s.at}</span>}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

export default function Chat() {
  const location = useLocation();
  const navigate = useNavigate();
  // Captured once from the upload handoff so the header keeps the folder name even
  // after we clear the navigation state when starting a fresh chat (see below).
  const [corpus] = useState<Corpus | null>(
    () => (location.state as Corpus | null) ?? null,
  );

  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string>(() => conversations[0].id);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [treeOpen, setTreeOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareHtml, setShareHtml] = useState("");
  const [resetting, setResetting] = useState(false);

  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [step, setStep] = useState(0);
  const [animatingId, setAnimatingId] = useState<number | null>(null);
  const [status, setStatus] = useState<IndexStatus | null>(null);

  const taRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stepTimer = useRef<number | null>(null);
  // The shuffled set of "thinking" lines for the current question.
  const thinkingLines = useRef<string[]>(THINKING_LINES);
  // Guards the one-time "start a fresh chat after an upload" handoff below.
  const startedFreshForUpload = useRef(false);

  const active =
    conversations.find((c) => c.id === activeId) ?? conversations[0];
  const messages = active.messages;

  const folderName = corpus?.folderName ?? "your documents";
  const docCount = corpus?.fileCount ?? status?.doc_count ?? 0;
  const hasIndex = docCount > 0 || (status?.built ?? false);

  // Persist conversations whenever they change.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    } catch {
      /* storage full / unavailable — non-fatal */
    }
  }, [conversations]);

  // Keep the active id pointing at a real conversation.
  useEffect(() => {
    if (!conversations.find((c) => c.id === activeId)) {
      setActiveId(conversations[0]?.id ?? "");
    }
  }, [conversations, activeId]);

  // Arriving straight from an upload (corpus handoff) should open a brand-new chat
  // session, not drop the user back into their previous conversation. Runs once.
  useEffect(() => {
    if (!corpus || startedFreshForUpload.current) return;
    startedFreshForUpload.current = true;

    const top = conversations[0];
    if (top && top.messages.length === 0) {
      // Already sitting in a fresh, empty chat — just focus it.
      setActiveId(top.id);
    } else {
      const fresh = newConversation();
      setConversations((cs) => [fresh, ...cs]);
      setActiveId(fresh.id);
    }

    // Consume the navigation state so a refresh doesn't spawn another new chat.
    navigate("/chat", { replace: true, state: null });
  }, [corpus, conversations, navigate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking, step, animatingId]);

  // While the latest answer is typing out, keep the view pinned to the bottom so
  // the streaming text stays visible as it grows.
  useEffect(() => {
    if (animatingId == null) return;
    const id = window.setInterval(() => {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }, 60);
    return () => window.clearInterval(id);
  }, [animatingId]);

  useEffect(() => {
    getIndexStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
    return () => {
      if (stepTimer.current !== null) window.clearInterval(stepTimer.current);
    };
  }, []);

  const patchActive = (fn: (c: Conversation) => Conversation) =>
    setConversations((cs) => cs.map((c) => (c.id === active.id ? fn(c) : c)));

  // Cleared when the latest answer finishes its typing reveal. Stable identity so
  // memoized ChatMessages don't re-render on every parent update.
  const stopTyping = useCallback(() => setAnimatingId(null), []);

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = taRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  };

  const resetComposer = () => {
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const send = async (preset?: string) => {
    const q = (preset ?? input).trim();
    if (!q || thinking) return;

    const userMsg: Message = { id: Date.now(), role: "user", content: q };
    patchActive((c) => ({
      ...c,
      title: c.messages.length === 0 ? deriveTitle(q) : c.title,
      messages: [...c.messages, userMsg],
    }));
    resetComposer();

    setThinking(true);
    setStep(0);
    thinkingLines.current = shuffle(THINKING_LINES);
    stepTimer.current = window.setInterval(() => {
      setStep((s) => s + 1);
    }, 1700);

    try {
      const res = await chat(q);
      const reply: Message = {
        id: Date.now() + 1,
        role: "assistant",
        content: res.answer,
        sources: res.sources.map((s) => ({
          file: s.doc_name,
          at: s.pages ? `lines ${s.pages}` : "",
        })),
        confidence: res.confidence ?? null,
        meta: {
          sections: res.meta.sections_used,
          branches: res.meta.docs_indexed,
        },
      };
      patchActive((c) => ({ ...c, messages: [...c.messages, reply] }));
      setAnimatingId(reply.id);
    } catch (err) {
      patchActive((c) => ({
        ...c,
        messages: [
          ...c.messages,
          {
            id: Date.now() + 1,
            role: "assistant",
            content:
              err instanceof Error
                ? err.message
                : "Something went wrong reaching the local model.",
          },
        ],
      }));
    } finally {
      if (stepTimer.current !== null) window.clearInterval(stepTimer.current);
      setThinking(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const startNewChat = () => {
    if (active.messages.length === 0) {
      setActiveId(active.id);
      resetComposer();
      return;
    }
    const c = newConversation();
    setConversations((cs) => [c, ...cs]);
    setActiveId(c.id);
    resetComposer();
  };

  const selectChat = (id: string) => {
    setActiveId(id);
    resetComposer();
  };

  const deleteChat = (id: string) => {
    setConversations((cs) => {
      const next = cs.filter((c) => c.id !== id);
      return next.length ? next : [newConversation()];
    });
  };

  const clearAll = () => {
    const c = newConversation();
    setConversations([c]);
    setActiveId(c.id);
    setSettingsOpen(false);
  };

  const handleResetIndex = async () => {
    if (resetting) return;
    const ok = window.confirm(
      "Reset the index? This permanently clears every indexed document (your chat " +
        "history is kept). You'll upload documents again to ask new questions.",
    );
    if (!ok) return;
    setResetting(true);
    try {
      await resetIndex();
      setStatus({
        built: false,
        doc_count: 0,
        documents: [],
        store_path: status?.store_path ?? "",
      });
      setSettingsOpen(false);
      navigate("/upload", { replace: true });
    } catch (err) {
      window.alert(`Could not reset the index: ${(err as Error).message}`);
    } finally {
      setResetting(false);
    }
  };

  const exportBundle = async () => {
    setPlusOpen(false);
    let store: unknown = null;
    try {
      store = (await exportStore()).store;
    } catch {
      // No index built yet — export the conversation alone (transcript only).
    }
    const bundle = {
      format: "ragindex.bundle",
      version: 1,
      exported_at: new Date().toISOString(),
      title: active.title,
      corpus: { folderName, doc_count: docCount },
      conversation: active,
      store,
    };
    const blob = new Blob([JSON.stringify(bundle, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(active.title || "ragindex-chat")
      .replace(/[^\w-]+/g, "-")
      .slice(0, 40)}.ragindex.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const openShare = async () => {
    setPlusOpen(false);
    const { buildShareHtml } = await import("@/lib/shareHtml");
    const html = buildShareHtml(
      active.title || "Turing Tree conversation",
      active.messages.map((m) => ({
        role: m.role,
        content: m.content,
        sources: m.sources,
      })),
      { docCount, folderName },
    );
    setShareHtml(html);
    setShareOpen(true);
  };

  const importBundle = async (text: string) => {
    let bundle: {
      conversation?: { title?: string; messages?: Message[]; createdAt?: number };
      store?: { documents?: Record<string, unknown> };
    };
    try {
      bundle = JSON.parse(text);
    } catch {
      throw new Error("That doesn't look like a bundle — invalid JSON.");
    }
    const conv = bundle?.conversation;
    if (!conv || !Array.isArray(conv.messages)) {
      throw new Error("No conversation found in this bundle.");
    }
    if (bundle.store?.documents) {
      await importStore(bundle.store);
    }
    const restored: Conversation = {
      id: uid(),
      title: conv.title || "Imported chat",
      messages: conv.messages,
      createdAt: conv.createdAt || Date.now(),
    };
    setConversations((cs) => [restored, ...cs]);
    setActiveId(restored.id);
    setSidebarOpen(false);
    getIndexStatus()
      .then(setStatus)
      .catch(() => { });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground antialiased">
      {/* ── Sidebar ─────────────────────────────────────────────── */}
      <aside
        className={`h-full shrink-0 overflow-hidden border-r border-line/10 bg-surface-1 transition-[width] duration-300 ease-out ${sidebarOpen ? "w-[268px]" : "w-0"
          }`}
      >
        <div className="flex h-full w-[268px] flex-col">
          {/* Top: account + collapse */}
          <div className="flex items-center gap-2.5 px-3 py-3">
            <button
              onClick={() => setSidebarOpen(false)}
              aria-label="Collapse sidebar"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <Menu className="h-[18px] w-[18px]" />
            </button>
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-[13px] font-semibold text-background">
                Y
              </div>
              <div className="min-w-0 leading-tight">
                <p className="truncate text-[13px] font-medium text-foreground/90">
                  You
                </p>
                <p className="truncate text-[11px] text-muted">Local · on-device</p>
              </div>
            </div>
          </div>

          {/* New chat */}
          <div className="px-3 pb-1">
            <button
              onClick={startNewChat}
              className="flex w-full items-center gap-2 rounded-xl border border-line/15 bg-surface-2/50 px-3 py-2.5 text-[13px] font-medium text-foreground/90 transition-colors hover:border-line/30 hover:bg-surface-2"
            >
              <Plus className="h-4 w-4" />
              New chat
            </button>
          </div>

          {/* Past chats */}
          <nav className="thin-scroll mt-2 flex-1 overflow-y-auto px-2">
            <p className="px-2 pb-1 pt-2 text-[11px] uppercase tracking-[0.14em] text-muted/55">
              Recent
            </p>
            {conversations.map((c) => {
              const activeChat = c.id === active.id;
              return (
                <div key={c.id} className="group relative">
                  <button
                    onClick={() => selectChat(c.id)}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 pr-9 text-left transition-colors ${activeChat
                      ? "bg-surface-2 text-foreground"
                      : "text-muted hover:bg-surface-2/50 hover:text-foreground"
                      }`}
                  >
                    <MessageSquare className="h-[15px] w-[15px] shrink-0 opacity-70" />
                    <span className="flex-1 truncate text-[13px]">
                      {c.title || "New chat"}
                    </span>
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteChat(c.id);
                    }}
                    aria-label="Delete chat"
                    className="absolute right-1.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-muted opacity-0 transition-all hover:bg-surface-3 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <Trash2 className="h-[14px] w-[14px]" />
                  </button>
                </div>
              );
            })}
          </nav>

          {/* Bottom: settings */}
          <div className="relative border-t border-line/10 p-2">
            {settingsOpen && (
              <>
                <button
                  aria-hidden="true"
                  tabIndex={-1}
                  onClick={() => setSettingsOpen(false)}
                  className="fixed inset-0 z-10 cursor-default"
                />
                <div className="absolute bottom-[calc(100%+6px)] left-2 right-2 z-20 overflow-hidden rounded-xl border border-line/15 bg-surface-2 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.8)]">
                  <Link
                    to="/upload"
                    className="flex items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                  >
                    <UploadCloud className="h-4 w-4 text-muted" />
                    New index
                  </Link>
                  <button
                    onClick={() => {
                      setSettingsOpen(false);
                      navigate("/upload");
                    }}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                  >
                    <Upload className="h-4 w-4 text-muted" />
                    Upload
                  </button>
                  <button
                    onClick={() => {
                      setSettingsOpen(false);
                      setImportOpen(true);
                    }}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                  >
                    <FolderInput className="h-4 w-4 text-muted" />
                    Resume from bundle
                  </button>
                  <button
                    onClick={handleResetIndex}
                    disabled={resetting}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-rose-300/90 transition-colors hover:bg-surface-3 disabled:opacity-60"
                  >
                    <RotateCcw className="h-4 w-4" />
                    {resetting ? "Resetting index…" : "Reset index"}
                  </button>
                  <button
                    onClick={clearAll}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                  >
                    <Trash2 className="h-4 w-4 text-muted" />
                    Clear conversations
                  </button>
                  <div className="border-t border-line/10 px-3.5 py-2.5 text-[11px] leading-relaxed text-muted/70">
                    Encrypted · nothing leaves your machine.
                  </div>
                </div>
              </>
            )}
            <button
              onClick={() => setSettingsOpen((o) => !o)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-muted transition-colors hover:bg-surface-2/60 hover:text-foreground"
            >
              <Settings className="h-[17px] w-[17px]" />
              Settings
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main ────────────────────────────────────────────────── */}
      <div className="relative flex h-full flex-1 flex-col">
        {/* Compose / new chat — sits just below the hamburger while the sidebar is closed */}
        {!sidebarOpen && (
          <button
            onClick={startNewChat}
            aria-label="New chat"
            title="New chat"
            className="group absolute left-4 top-[52px] z-20 flex h-8 w-8 items-center justify-center rounded-lg transition-colors hover:bg-surface-2"
          >
            <img
              src="/write-svgrepo-com.svg"
              alt=""
              className="h-[18px] w-[18px] opacity-65 [filter:invert(1)] transition-opacity group-hover:opacity-100"
            />
          </button>
        )}
        {/* Header */}
        <header className="flex shrink-0 items-center gap-3 px-4 py-3">
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <Menu className="h-[18px] w-[18px]" />
            </button>
          )}
          <Link to="/" className="flex items-center gap-2">
            <BrandMark className="h-5 w-5" />
          </Link>
          <span className="min-w-0 flex-1 truncate text-[13px] text-muted">
            {messages.length ? active.title : "New chat"}
          </span>
          {hasIndex && (
            <span className="hidden items-center gap-2 rounded-full border border-line/15 bg-surface-1 px-3 py-1.5 text-[12px] text-muted sm:flex">
              <GradientDot className="h-1.5 w-1.5" />
              <span className="max-w-[160px] truncate text-foreground/85">
                {folderName}
              </span>
              <span className="text-muted/40">·</span>
              {docCount.toLocaleString()} {plural(docCount, "doc")}
            </span>
          )}
          <button
            onClick={() => setTreeOpen(true)}
            aria-label="Visualize the reasoning tree"
            title="Reasoning tree"
            className="group flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-surface-2"
          >
            <img
              src="/tree-with-hierarchical-network-svgrepo-com.svg"
              alt=""
              className="h-[18px] w-[18px] opacity-70 [filter:invert(1)] transition-opacity group-hover:opacity-100"
            />
          </button>
        </header>

        {/* Conversation */}
        <main className="thin-scroll relative flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-6 py-8">
            {messages.length === 0 ? (
              /* Welcome */
              <div className="animate-fade-up pt-10">
                <BrandMark className="h-9 w-9" />
                <h1 className="mt-6 font-display text-[34px] font-medium leading-[1.1] tracking-tight">
                  Ask your index.
                </h1>
                <p className="mt-3 max-w-md text-[15px] leading-7 text-muted">
                  {hasIndex ? (
                    <>
                      <span className="text-foreground/90">{folderName}</span> is a
                      reasoning tree of {docCount.toLocaleString()}{" "}
                      {plural(docCount, "document")}. Every answer is retrieved and
                      reasoned over your files, on this machine.
                    </>
                  ) : (
                    "No documents are indexed yet. Upload a folder and Turing Tree will grow a reasoning tree you can question here."
                  )}
                </p>

                {hasIndex ? (
                  <div className="mt-8 space-y-2.5">
                    {EXAMPLES.map((ex, i) => (
                      <button
                        key={ex}
                        onClick={() => send(ex)}
                        className="group flex w-full animate-fade-up items-center gap-3 rounded-2xl border border-line/12 bg-surface-1 px-4 py-3.5 text-left transition-colors hover:border-line/25 hover:bg-surface-2"
                        style={{ animationDelay: `${0.06 + i * 0.05}s` }}
                      >
                        <span className="text-[14.5px] text-foreground/85">{ex}</span>
                        <ArrowRight className="ml-auto h-4 w-4 shrink-0 text-muted/50 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
                      </button>
                    ))}
                  </div>
                ) : (
                  <Link
                    to="/upload"
                    className="mt-8 inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-[#6366f1] via-[#a855f7] to-[#fcd34d] px-5 py-3 text-[14px] font-semibold text-background transition-opacity hover:opacity-95"
                  >
                    <UploadCloud className="h-4 w-4" />
                    Upload a folder
                  </Link>
                )}
              </div>
            ) : (
              <div className="space-y-7">
                {messages.map((msg) => (
                  <ChatMessage
                    key={msg.id}
                    msg={msg}
                    animate={msg.id === animatingId}
                    onTyped={stopTyping}
                  />
                ))}

                {thinking && (
                  <div className="flex animate-fade-up-sm gap-3.5">
                    <BrandMark className="h-7 w-7 shrink-0" />
                    <div className="mt-1 flex items-center gap-2.5 text-[13px] text-muted">
                      <span className="flex gap-1">
                        {[0, 1, 2].map((i) => (
                          <GradientDot key={i} className="h-1.5 w-1.5 animate-typing" />
                        ))}
                      </span>
                      <span key={step} className="animate-fade-up-sm">
                        {thinkingLines.current[step % thinkingLines.current.length]}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </main>

        {/* Composer */}
        <div className="shrink-0 px-4 pb-5 pt-1">
          <div className="mx-auto w-full max-w-3xl">
            <div className="flex items-end gap-1.5 rounded-[24px] border border-line/15 bg-surface-1 px-2.5 py-2 transition-colors focus-within:border-accent/40">
              {/* + actions menu */}
              <div className="relative shrink-0">
                {plusOpen && (
                  <>
                    <button
                      aria-hidden="true"
                      tabIndex={-1}
                      onClick={() => setPlusOpen(false)}
                      className="fixed inset-0 z-10 cursor-default"
                    />
                    <div className="absolute bottom-[calc(100%+12px)] left-0 z-20 w-48 overflow-hidden rounded-xl border border-line/15 bg-surface-2 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.8)]">
                      <button
                        onClick={() => {
                          setPlusOpen(false);
                          navigate("/upload");
                        }}
                        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                      >
                        <Paperclip className="h-4 w-4 text-muted" />
                        Upload files
                      </button>
                      <button
                        onClick={exportBundle}
                        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                      >
                        <Download className="h-4 w-4 text-muted" />
                        Export
                      </button>
                      <button
                        onClick={openShare}
                        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px] text-foreground/85 transition-colors hover:bg-surface-3"
                      >
                        <Share2 className="h-4 w-4 text-muted" />
                        Share
                      </button>
                    </div>
                  </>
                )}
                <button
                  onClick={() => setPlusOpen((o) => !o)}
                  aria-label="Add"
                  className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
                >
                  <Plus className="h-[18px] w-[18px]" />
                </button>
              </div>
              <textarea
                ref={taRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                rows={1}
                placeholder={
                  hasIndex ? `Ask about ${folderName}…` : "Upload a folder to ask…"
                }
                className="thin-scroll max-h-[200px] flex-1 resize-none bg-transparent px-1 py-1.5 text-[15px] leading-6 text-foreground placeholder:text-muted/60 focus:outline-none"
              />
              <button
                onClick={() => send()}
                disabled={!input.trim() || thinking}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground text-background transition-opacity duration-200 hover:opacity-90 disabled:bg-surface-3 disabled:text-muted/50"
                aria-label="Send"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-2.5 text-center text-[11px] text-muted/70">
              Answers grounded in your files · runs fully on your machine
            </p>
          </div>
        </div>
      </div>

      {treeOpen && <TreeView onClose={() => setTreeOpen(false)} />}
      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImport={importBundle}
        />
      )}
      {shareOpen && (
        <ShareDialog
          html={shareHtml}
          title={active.title}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
}
