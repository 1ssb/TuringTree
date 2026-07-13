import { describe, expect, it } from "vitest";

import { buildShareHtml, type ShareMessage } from "@/lib/shareHtml";

const convo: ShareMessage[] = [
  { role: "user", content: "What is photosynthesis?" },
  {
    role: "assistant",
    content: "It is **how plants** make food.",
    sources: [{ file: "bio.md", at: "lines 3-9" }],
  },
];

describe("buildShareHtml", () => {
  it("brands the page as 'Turing Tree' and never leaks 'RagIndex'", () => {
    const html = buildShareHtml("My chat", convo, {});
    expect(html).toContain("Turing Tree");
    expect(html).not.toContain("RagIndex");
    // document title + footer both carry the brand name
    expect(html).toMatch(/<title>[^<]*Turing Tree<\/title>/);
    expect(html).toContain("Generated with <b>Turing Tree</b>");
  });

  it("falls back to a 'Turing Tree conversation' title when none is given", () => {
    const html = buildShareHtml("", [], {});
    expect(html).toContain("Turing Tree conversation");
  });

  it("escapes HTML in user content so a shared page can't run injected script", () => {
    const html = buildShareHtml("t", [
      { role: "user", content: "<script>alert('x')</script>" },
    ]);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>alert");
  });

  it("renders assistant Markdown to semantic HTML", () => {
    const html = buildShareHtml("t", convo, {});
    expect(html).toContain("<strong>how plants</strong>");
  });

  it("renders grounded sources as chips with the file and location", () => {
    const html = buildShareHtml("t", convo, {});
    expect(html).toContain("Grounded in");
    expect(html).toContain("bio.md");
    expect(html).toContain("lines 3-9");
  });

  it("includes the document count when provided in meta", () => {
    const html = buildShareHtml("t", convo, { docCount: 12 });
    expect(html).toContain("12 documents");
  });
});
