import { afterEach, expect, jest, test } from "@jest/globals";
import { GET, POST } from "./route";

const base = "http://localhost:3000/api/backend";
const context = (...path: string[]) => ({ params: Promise.resolve({ path }) });

afterEach(() => { jest.restoreAllMocks(); });

test("does not forward internal Inventory mutations", async () => {
  const fetchMock = jest.spyOn(globalThis, "fetch");
  const path = ["inventory", "flights", "flight-204", "seats", "1A", "release"];
  const response = await POST(new Request(`${base}/${path.join("/")}`, { method: "POST" }), context(...path));
  expect(response.status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
});

test("forwards the reservation credential only in the authorization header", async () => {
  const fetchMock = jest.spyOn(globalThis, "fetch").mockResolvedValue(
    Response.json({ status: "CONFIRMED" }),
  );
  const request = new Request(`${base}/reservations/demo/confirm`, {
    method: "POST",
    headers: {
      Authorization: "Bearer test-only",
      "Idempotency-Key": "confirm-key",
      Cookie: "frontend-cookie=test-only",
    },
  });
  const response = await POST(request, context("reservations", "demo", "confirm"));
  const [target, options] = fetchMock.mock.calls[0];
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "CONFIRMED" });
  expect(new URL(String(target)).pathname).toMatch(/\/reservations\/demo\/confirm$/);
  expect(String(target)).not.toContain("test-only");
  expect(new Headers(options?.headers).get("authorization")).toBe("Bearer test-only");
  expect(new Headers(options?.headers).get("idempotency-key")).toBe("confirm-key");
  expect(new Headers(options?.headers).has("cookie")).toBe(false);
});

test("returns a 503 without upstream details when Inventory cannot be reached", async () => {
  jest.spyOn(globalThis, "fetch").mockRejectedValue(new Error("connection refused"));
  const path = ["inventory", "flights", "flight-204", "seats"];
  const response = await GET(new Request(`${base}/${path.join("/")}`), context(...path));
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ detail: "BACKEND_UNAVAILABLE" });
});
