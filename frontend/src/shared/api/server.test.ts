import { afterEach, expect, jest, test } from "@jest/globals";
import { searchFlights } from "./server";

const route = { origin: "BOG", destination: "MDE", departureDate: "2026-11-19" };

afterEach(() => { jest.restoreAllMocks(); });

test("requests the selected route and page from Inventory without caching", async () => {
  const body = { data: [], pagination: { page: 2, pageSize: 12, totalItems: 0, totalPages: 0 } };
  const fetchMock = jest.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(body));
  await expect(searchFlights(route, { page: 2, pageSize: 12 })).resolves.toEqual(body);
  const [target, options] = fetchMock.mock.calls[0];
  const url = new URL(String(target));
  expect(url.pathname).toMatch(/\/inventory\/flights$/);
  expect(Object.fromEntries(url.searchParams)).toEqual({ ...route, page: "2", pageSize: "12" });
  expect(options?.cache).toBe("no-store");
});

test("propagates an error when the flight catalog is unavailable", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
  await expect(searchFlights(route)).rejects.toThrow("BACKEND_HTTP_503");
});
