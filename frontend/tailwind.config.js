/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Stored as raw HSL triplets in index.css so "/<alpha-value>" enables
        // opacity modifiers like text-foreground/90 or via-foreground/20.
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        "hero-sub": "hsl(var(--hero-sub) / <alpha-value>)",
        // Elevation scale + accents (the app surfaces that lift off the base).
        "surface-1": "hsl(var(--surface-1) / <alpha-value>)",
        "surface-2": "hsl(var(--surface-2) / <alpha-value>)",
        "surface-3": "hsl(var(--surface-3) / <alpha-value>)",
        line: "hsl(var(--line) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        accent: "hsl(var(--accent) / <alpha-value>)",
      },
      fontFamily: {
        // Body font (bundled via @fontsource/geist-sans).
        sans: ["Geist Sans", "system-ui", "sans-serif"],
        // Headline font (loaded from Fontshare in index.html).
        display: ["General Sans", "system-ui", "sans-serif"],
      },
      keyframes: {
        // Logo marquee: scroll the (duplicated) row exactly half-way for a
        // seamless infinite loop.
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        // Sequential entrance used across the neutral screens.
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        // Smaller, snappier entrance for chat message rows.
        fadeUpSm: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        // Three-dot "AI is typing" bounce.
        typingBounce: {
          "0%, 100%": { transform: "translateY(0)", opacity: "0.25" },
          "50%": { transform: "translateY(-3px)", opacity: "0.75" },
        },
        // Floating success toast.
        toastIn: {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        // Upload arrow bobbing up while a file is being dropped.
        uploadBob: {
          "0%, 100%": { transform: "translateY(2px)", opacity: "0.55" },
          "50%": { transform: "translateY(-3px)", opacity: "1" },
        },
        // Indeterminate progress bar sliding across while indexing.
        indeterminate: {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(380%)" },
        },
      },
      animation: {
        marquee: "marquee 20s linear infinite",
        "fade-up": "fadeUp 0.55s ease both",
        "fade-up-sm": "fadeUpSm 0.25s ease both",
        typing: "typingBounce 1.3s ease-in-out infinite",
        "toast-in": "toastIn 0.35s ease both",
        "upload-bob": "uploadBob 1.1s ease-in-out infinite",
        indeterminate: "indeterminate 1.3s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
