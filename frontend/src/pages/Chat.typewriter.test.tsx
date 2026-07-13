import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { shuffle, THINKING_LINES, TypewriterAnswer } from "@/pages/Chat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("shuffle", () => {
  it("returns a permutation of the same elements without mutating the input", () => {
    const input = [1, 2, 3, 4, 5];
    const snapshot = [...input];
    const out = shuffle(input);

    expect(out).toHaveLength(input.length);
    expect([...out].sort((a, b) => a - b)).toEqual(
      [...input].sort((a, b) => a - b),
    );
    expect(input).toEqual(snapshot); // original array untouched
  });
});

describe("THINKING_LINES", () => {
  it("is a non-empty list of non-empty strings", () => {
    expect(Array.isArray(THINKING_LINES)).toBe(true);
    expect(THINKING_LINES.length).toBeGreaterThan(0);
    for (const line of THINKING_LINES) {
      expect(typeof line).toBe("string");
      expect(line.trim().length).toBeGreaterThan(0);
    }
  });
});

describe("TypewriterAnswer", () => {
  it("shows the full answer at once and calls onDone when reduced motion is preferred", () => {
    // Force prefers-reduced-motion so the component skips the timed reveal and
    // renders the complete Markdown immediately.
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: true,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    const onDone = vi.fn();
    const { container } = render(
      <TypewriterAnswer
        text="Plants make **food** from light."
        onDone={onDone}
      />,
    );

    expect(container.textContent).toContain("Plants make");
    expect(container.textContent).toContain("food");
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
