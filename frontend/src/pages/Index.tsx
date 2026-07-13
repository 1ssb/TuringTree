import { Link } from "react-router-dom";
import {
  ChevronDown,
  ArrowRight,
  FolderUp,
  GitBranch,
  MessagesSquare,
  Lock,
  Quote,
} from "lucide-react";

import { BackgroundVideo } from "@/components/BackgroundVideo";
import { Hero } from "@/components/Hero";
import { Wordmark } from "@/components/brand";
import StarBorder from "@/components/ui/StarBorder";

/** Looping hero background video. */
const VIDEO_URL =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_065045_c44942da-53c6-4804-b734-f9e07fc22e08.mp4";

const GITHUB_URL = "https://github.com/1ssb/TuringTree";

/** Small bordered eyebrow label that opens every section. */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line/20 bg-surface-1 px-3.5 py-1.5 text-[12px] font-medium uppercase tracking-[0.16em] text-accent/90">
      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
      {children}
    </span>
  );
}

/* ─────────────────────────── What it is ─────────────────────────── */

const VALUES = [
  {
    icon: GitBranch,
    title: "Vectorless",
    body: "Reasons over a hierarchical table-of-contents tree instead of nearest-neighbour vectors. No embeddings, no chunking by distance.",
  },
  {
    icon: Lock,
    title: "Fully local",
    body: "Ollama and Qwen run on your machine. There are no API keys, and not a single document ever leaves your computer.",
  },
  {
    icon: Quote,
    title: "Grounded",
    body: "Every answer cites the exact sections it walked to get there — so you can always check the source.",
  },
];

function About() {
  return (
    <section
      id="about"
      className="relative flex min-h-screen snap-start snap-always flex-col justify-center border-t border-line/10 px-6 py-20"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-0 h-72 w-[680px] -translate-x-1/2 rounded-full opacity-20 blur-[130px]"
        style={{ background: "radial-gradient(circle, #6366f1, transparent 70%)" }}
      />
      <div className="relative mx-auto w-full max-w-6xl">
        <Eyebrow>What it is</Eyebrow>
        <h2 className="mt-5 max-w-2xl font-display text-4xl font-medium leading-[1.08] tracking-tight sm:text-5xl">
          RAG that reasons, not retrieves.
        </h2>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-muted">
          Turing Tree builds a reasoning tree over your documents and walks it to
          find answers — the way a person scans a table of contents. It runs
          entirely on your machine, so your files stay yours.
        </p>

        <div className="mt-12 grid gap-4 sm:grid-cols-3">
          {VALUES.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-2xl border border-line/15 bg-surface-1 p-6 transition-colors duration-200 hover:border-line/30"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-line/15 bg-surface-2 text-accent">
                <Icon className="h-[18px] w-[18px]" />
              </span>
              <h3 className="mt-5 font-display text-xl font-medium tracking-tight">
                {title}
              </h3>
              <p className="mt-2 text-[15px] leading-7 text-muted">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─────────────────────────── How it works ─────────────────────────── */

const STEPS = [
  {
    n: "01",
    icon: FolderUp,
    title: "Feed it a folder",
    body: "Drop in your documents. Turing Tree reads each file on your machine.",
    to: "/upload",
    cta: "Open uploader",
  },
  {
    n: "02",
    icon: GitBranch,
    title: "It grows a tree",
    body: "PageIndex turns them into a reasoning tree of sections and summaries.",
  },
  {
    n: "03",
    icon: MessagesSquare,
    title: "Ask anything",
    body: "Questions walk the tree to a grounded, cited answer — all offline.",
    to: "/chat",
    cta: "Open chat",
  },
];

function HowItWorks() {
  return (
    <section id="how" className="flex min-h-screen snap-start snap-always flex-col justify-center border-t border-line/10 px-6 py-20">
      <div className="mx-auto w-full max-w-6xl">
        <Eyebrow>How it works</Eyebrow>
        <h2 className="mt-5 max-w-2xl font-display text-4xl font-medium leading-[1.08] tracking-tight sm:text-5xl">
          From folder to grounded answer.
        </h2>

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {STEPS.map(({ n, icon: Icon, title, body, to, cta }) => (
            <div
              key={n}
              className="flex flex-col rounded-2xl border border-line/15 bg-surface-1 p-6 transition-colors duration-200 hover:border-line/30"
            >
              <div className="flex items-center justify-between">
                <span className="font-display text-sm tabular-nums text-muted">
                  {n}
                </span>
                <Icon className="h-[18px] w-[18px] text-accent" />
              </div>
              <h3 className="mt-6 font-display text-xl font-medium tracking-tight">
                {title}
              </h3>
              <p className="mt-2 flex-1 text-[15px] leading-7 text-muted">
                {body}
              </p>
              {to && (
                <Link
                  to={to}
                  className="group mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-accent transition-colors hover:text-foreground"
                >
                  {cta}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─────────────────────────── The stack ─────────────────────────── */

const STACK = [
  { name: "Ollama", role: "Local runtime" },
  { name: "Qwen", role: "Chat + embed" },
  { name: "PageIndex", role: "Reasoning tree" },
  { name: "Hugging Face", role: "Dataset" },
  { name: "LiteLLM", role: "Model routing" },
  { name: "FastAPI", role: "Serving" },
];

function Stack() {
  return (
    <section className="flex min-h-screen snap-start snap-always flex-col justify-center border-t border-line/10 px-6 py-20">
      <div className="mx-auto w-full max-w-6xl">
        <Eyebrow>Under the hood</Eyebrow>
        <h2 className="mt-5 max-w-2xl font-display text-4xl font-medium leading-[1.08] tracking-tight sm:text-5xl">
          A fully local, open stack.
        </h2>

        <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {STACK.map(({ name, role }) => (
            <div
              key={name}
              className="rounded-xl border border-line/15 bg-surface-1 p-4 transition-colors duration-200 hover:border-line/30"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-line/15 bg-surface-2 text-sm font-semibold text-foreground">
                {name[0]}
              </span>
              <p className="mt-3 text-[15px] font-medium leading-tight">{name}</p>
              <p className="mt-0.5 text-xs text-muted">{role}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─────────────────────────── Final CTA ─────────────────────────── */

function FinalCta() {
  return (
    <section className="relative flex flex-1 items-center justify-center px-6 py-16">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-72 w-[700px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-25 blur-[140px]"
        style={{ background: "radial-gradient(circle, #a855f7, transparent 70%)" }}
      />
      <div className="relative mx-auto max-w-2xl text-center">
        <h2 className="font-display text-4xl font-medium leading-[1.06] tracking-tight sm:text-5xl">
          Index your first folder.
        </h2>
        <p className="mx-auto mt-4 max-w-md text-lg leading-8 text-muted">
          Build a reasoning tree from your documents in a minute — everything
          stays on your machine.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <StarBorder
            as={Link}
            to="/upload"
            color="#a78bfa"
            speed="5s"
            thickness={2}
            className="group"
          >
            <span className="flex items-center gap-2 font-medium">
              Get started
              <ArrowRight className="h-[18px] w-[18px] transition-transform duration-200 group-hover:translate-x-0.5" />
            </span>
          </StarBorder>
          <Link
            to="/chat"
            className="text-sm font-medium text-muted transition-colors hover:text-foreground"
          >
            or open the chat →
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─────────────────────────── Footer ─────────────────────────── */

const FOOTER_LINKS: {
  title: string;
  links: { label: string; to: string; ext?: boolean }[];
}[] = [
  {
    title: "Product",
    links: [
      { label: "Upload", to: "/upload" },
      { label: "Chat", to: "/chat" },
    ],
  },
  {
    title: "Learn",
    links: [
      { label: "About", to: "#about" },
      { label: "How it works", to: "#how" },
    ],
  },
  {
    title: "Source",
    links: [{ label: "GitHub", to: GITHUB_URL, ext: true }],
  },
];

function Footer() {
  return (
    <footer className="border-t border-line/10 px-6 py-14">
      <div className="mx-auto flex max-w-6xl flex-col gap-12 sm:flex-row sm:justify-between">
        <div className="max-w-xs">
          <Wordmark />
          <p className="mt-4 text-sm leading-6 text-muted">
            Vectorless, reasoning-based RAG. Runs fully on your machine — no API
            keys, nothing leaves your computer.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-10">
          {FOOTER_LINKS.map((col) => (
            <div key={col.title}>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-foreground/50">
                {col.title}
              </p>
              <ul className="mt-4 space-y-3">
                {col.links.map((l) => (
                  <li key={l.label}>
                    {l.ext || l.to.startsWith("#") ? (
                      <a
                        href={l.to}
                        {...(l.ext ? { target: "_blank", rel: "noreferrer" } : {})}
                        className="text-sm text-muted transition-colors hover:text-foreground"
                      >
                        {l.label}
                      </a>
                    ) : (
                      <Link
                        to={l.to}
                        className="text-sm text-muted transition-colors hover:text-foreground"
                      >
                        {l.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="mx-auto mt-12 flex max-w-6xl items-center justify-between border-t border-line/10 pt-6 text-xs text-muted">
        <span>Turing Tree</span>
        <span>Runs fully on your machine.</span>
      </div>
    </footer>
  );
}

/* ─────────────────────────── Page ─────────────────────────── */

export default function Index() {
  return (
    <div className="relative h-screen snap-y snap-mandatory overflow-y-scroll overflow-x-hidden bg-background text-foreground antialiased">
      {/* ── Hero ── */}
      <section className="relative flex min-h-screen snap-start snap-always flex-col overflow-hidden">
        <BackgroundVideo src={VIDEO_URL} />

        {/* centered glow behind the hero */}
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-[527px] w-[984px] -translate-x-1/2 -translate-y-1/2 bg-gray-950 opacity-90 blur-[82px]" />

        {/* minimal brand (no nav) */}
        <header className="relative z-10 px-8 py-6">
          <Link to="/" className="inline-block rounded-lg outline-none">
            <Wordmark />
          </Link>
        </header>

        {/* hero content */}
        <div className="relative z-10 flex flex-1 items-center justify-center">
          <Hero />
        </div>

        {/* scroll cue */}
        <a
          href="#about"
          className="group relative z-10 mx-auto mb-10 flex flex-col items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted transition-colors hover:text-foreground"
        >
          Scroll
          <ChevronDown className="h-4 w-4 animate-bounce text-accent" />
        </a>
      </section>

      <About />
      <HowItWorks />
      <Stack />

      {/* Final snap section: CTA centered with the footer beneath */}
      <section className="flex min-h-screen snap-start snap-always flex-col border-t border-line/10">
        <FinalCta />
        <Footer />
      </section>
    </div>
  );
}
