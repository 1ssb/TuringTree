import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("cn", () => {
  it("joins truthy class names and drops falsey ones", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("lets the last conflicting Tailwind class win (tailwind-merge)", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
    expect(cn("text-sm", "text-lg")).toBe("text-lg");
  });

  it("supports clsx object + array syntax", () => {
    expect(cn({ "is-open": true, "is-closed": false })).toBe("is-open");
    expect(cn(["a", "b"], "c")).toBe("a b c");
  });
});
