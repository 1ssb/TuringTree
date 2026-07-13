import { cn } from "@/lib/utils";

/**
 * Shared brand marks for the app screens, drawn in the landing's
 * indigo -> purple -> amber "Turing Tree" gradient so /upload and /chat read as
 * the same product as the hero.
 */

/**
 * BrandMark — a minimal, balanced "reasoning tree": a grounded root that
 * branches symmetrically into a small canopy of gradient nodes. The symmetry +
 * grounded base read as stable and trustworthy; the structure uses
 * `currentColor` (so it inherits the surrounding text color) while the canopy
 * carries the Turing-Tree gradient.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn("h-8 w-8 text-foreground", className)}
    >
      <path
        d="M10.5 29h11M16 26v-8M16 18l-6-4.5M16 18l6-4.5M10 13.5l-3.5-5.5M10 13.5l3.5-5.5M22 13.5l-3.5-5.5M22 13.5l3.5-5.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="26" r="2" fill="currentColor" />
      <circle cx="6.5" cy="8" r="1.85" fill="url(#treeGrad)" />
      <circle cx="13.5" cy="8" r="1.85" fill="url(#treeGrad)" />
      <circle cx="18.5" cy="8" r="1.85" fill="url(#treeGrad)" />
      <circle cx="25.5" cy="8" r="1.85" fill="url(#treeGrad)" />
      <defs>
        <linearGradient
          id="treeGrad"
          x1="4"
          y1="6"
          x2="28"
          y2="10"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#6366f1" />
          <stop offset="0.5" stopColor="#a855f7" />
          <stop offset="1" stopColor="#fcd34d" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/** Brand glyph + "Turing Tree" wordmark in the display face. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark className="h-7 w-7" />
      <span className="font-display text-xl font-semibold tracking-tight text-foreground">
        Turing Tree
      </span>
    </span>
  );
}
