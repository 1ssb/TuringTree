import { Link } from "react-router-dom";

import StarBorder from "@/components/ui/StarBorder";

/**
 * ArrowRight — a small inline SVG arrow (NOT an icon font / image), shown after
 * the CTA label. It nudges to the right on hover via the parent button's
 * `group` class.
 */
function ArrowRight() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="transition-transform duration-200 group-hover:translate-x-0.5"
      aria-hidden="true"
    >
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}

/**
 * Hero
 * ----
 * The centered headline + subtitle + call-to-action. The "Tree" word uses a
 * clipped gradient (indigo -> purple -> amber).
 */
export function Hero() {
  return (
    <div className="relative z-10 flex flex-col items-center text-center">
      <h1 className="font-display text-[220px] font-normal leading-[1.02] tracking-[-0.024em]">
        <span className="block text-foreground">Turing</span>
        <span
          className="block bg-clip-text text-transparent"
          style={{
            backgroundImage:
              "linear-gradient(to left, #6366f1, #a855f7, #fcd34d)",
          }}
        >
          Tree
        </span>
      </h1>

      <p className="mt-[9px] max-w-2xl text-balance text-lg leading-8 text-hero-sub opacity-80">
        No vectors. No chunking. No blind trust.
      </p>

      <StarBorder
        as={Link}
        to="/upload"
        color="#a78bfa"
        speed="5s"
        thickness={2}
        className="group mt-[25px]"
      >
        <span className="flex items-center gap-2 font-medium">
          Try it out
          <ArrowRight />
        </span>
      </StarBorder>
    </div>
  );
}
