import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Button — a small shadcn-style button driven by class-variance-authority.
 *
 * The base classes give every button a pill shape and sensible default padding.
 * Because we merge classes with `cn` (tailwind-merge), any padding/size passed
 * through `className` cleanly overrides the defaults below.
 */
const buttonVariants = cva(
  "group inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        // Solid light button (kept for completeness / future use).
        default: "bg-foreground text-background hover:bg-foreground/90",
        // The hero's frosted glass button used by the navbar + CTA.
        heroSecondary:
          "liquid-glass text-foreground transition-all hover:bg-white/[0.06]",
        // The "Turing Tree" gradient fill — used for one primary action.
        heroPrimary:
          "bg-gradient-to-r from-[#6366f1] via-[#a855f7] to-[#fcd34d] text-background font-semibold shadow-[0_8px_30px_-8px_rgba(168,85,247,0.5)] transition-opacity hover:opacity-95",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the child element (e.g. an <a>) instead of a <button>. */
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
