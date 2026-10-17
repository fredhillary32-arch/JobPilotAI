import { afterEach, expect, it, vi } from "vitest";

import { api, ApiError, REQUEST_TIMEOUT_MS } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("ends a request that never answers with a readable timeout error", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
  })));
  const pending = api.listJobs("profile-1").catch((error: unknown) => error);
  await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
  const error = await pending;
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).message).toMatch(/did not respond within 90 seconds\. Nothing you entered was lost/);
});

it("does not time out a request that answers in time", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
  await expect(api.listJobs("profile-1")).resolves.toEqual([]);
});
