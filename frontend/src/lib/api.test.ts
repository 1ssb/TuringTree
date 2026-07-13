import { afterEach, describe, expect, it, vi } from "vitest";

import { chat, getIndexStatus } from "@/lib/api";

/** Build a stubbed fetch that resolves once with the given JSON payload. */
function mockFetch(payload: unknown, ok = true, status = 200) {
  const res = { ok, status, json: async () => payload } as unknown as Response;
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => res);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("getIndexStatus GETs /api/index/status and returns parsed JSON", async () => {
    const payload = {
      built: true,
      doc_count: 3,
      documents: [],
      store_path: "/x",
    };
    const fetchMock = mockFetch(payload);
    vi.stubGlobal("fetch", fetchMock);

    const result = await getIndexStatus();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/index/status");
    expect(result).toEqual(payload);
  });

  it("chat POSTs { message, top_k } as JSON and returns the answer", async () => {
    const payload = {
      answer: "hello",
      sources: [],
      meta: { docs_indexed: 1, sections_used: 2 },
    };
    const fetchMock = mockFetch(payload);
    vi.stubGlobal("fetch", fetchMock);

    const result = await chat("hi there", 5);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      message: "hi there",
      top_k: 5,
    });
    expect(result.answer).toBe("hello");
  });

  it("throws the server-provided detail on a non-OK response", async () => {
    const fetchMock = mockFetch({ detail: "index not built" }, false, 400);
    vi.stubGlobal("fetch", fetchMock);

    await expect(chat("q")).rejects.toThrow("index not built");
  });
});
