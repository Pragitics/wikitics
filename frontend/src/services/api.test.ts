import { afterEach, describe, expect, it, vi } from "vitest";
import { api, CONNECTION_INTERRUPTED_MESSAGE } from "./api";

describe("fetchWithRetry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rethrows an abort untouched instead of retrying it", async () => {
    // Stopping the mic or barging in aborts the in-flight turn. That must stay an
    // AbortError so the caller can tell a deliberate stop from a real failure.
    const abortError = new DOMException("The user aborted a request.", "AbortError");
    const fetchMock = vi.fn().mockRejectedValue(abortError);
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    const promise = api.askVoiceTranscriptStream("t", "s", "hello", () => {}, controller.signal);

    await expect(promise).rejects.toBe(abortError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries a genuine network failure once, then reports it as a connection drop", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.workspaces("token")).rejects.toThrow(CONNECTION_INTERRUPTED_MESSAGE);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("recovers when a retried request succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "ws-1" }]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.workspaces("token")).resolves.toEqual([{ id: "ws-1" }]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
