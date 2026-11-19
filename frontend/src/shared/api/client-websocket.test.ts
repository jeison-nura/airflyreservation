/**
 * @jest-environment jsdom
 * @jest-environment-options {"url":"https://frontend.example.test"}
 */

import { afterEach, expect, jest, test } from "@jest/globals";
import { apiWebSocketBaseUrl } from "./client";

afterEach(() => { jest.restoreAllMocks(); });

test("uses a secure WebSocket on an HTTPS page unless configured explicitly", () => {
  jest.replaceProperty(process, "env", { ...process.env, NEXT_PUBLIC_API_WS_URL: undefined });
  expect(apiWebSocketBaseUrl()).toBe("wss://localhost:8000/api/v1");
  process.env.NEXT_PUBLIC_API_WS_URL = "wss://inventory.example.test/api/v1/";
  expect(apiWebSocketBaseUrl()).toBe("wss://inventory.example.test/api/v1");
});
