/** @jest-environment jsdom */

import { afterEach, beforeAll, beforeEach, expect, jest, test } from "@jest/globals";
import type { getFlightSeats } from "./client";
import type { FlightSeat } from "./contracts";

const getSeats = jest.fn<typeof getFlightSeats>();
let observeFlightSeats: typeof import("./observe-flight-seats").observeFlightSeats;

beforeAll(async () => {
  jest.doMock("./client", () => ({
    getFlightSeats: getSeats,
    apiWebSocketBaseUrl: () => "ws://localhost:8000/api/v1",
  }));
  ({ observeFlightSeats } = await import("./observe-flight-seats"));
});

const available: FlightSeat[] = [{ seatNumber: "1A", status: "AVAILABLE" }];
const held: FlightSeat[] = [{ seatNumber: "1A", status: "HELD" }];
const originalWebSocket = globalThis.WebSocket;

class TestSocket {
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static sockets: TestSocket[] = [];
  readyState = 0;
  onopen?: () => void;
  onclose?: () => void;
  onmessage?: (message: { data: string }) => void;

  constructor() {
    TestSocket.sockets.push(this);
  }

  open() {
    this.readyState = TestSocket.OPEN;
    this.onopen?.();
  }

  close() {
    this.readyState = TestSocket.CLOSED;
    this.onclose?.();
  }

  sendUpdate(status: FlightSeat["status"]) {
    this.onmessage?.({
      data: JSON.stringify({ type: "seat.updated", flightId: "flight-204", seatNumber: "1A", status }),
    });
  }
}

beforeEach(() => {
  jest.useFakeTimers();
  TestSocket.sockets = [];
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: TestSocket });
});

afterEach(() => {
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: originalWebSocket });
  jest.useRealTimers();
  jest.resetAllMocks();
});

test("uses HTTP on startup and disconnect, then reconnects and stops on cleanup", async () => {
  getSeats.mockResolvedValue(available);
  const onSeats = jest.fn();
  const observer = observeFlightSeats("flight-204", onSeats, jest.fn());
  try {
    await jest.advanceTimersByTimeAsync(0);
    expect(onSeats).toHaveBeenLastCalledWith(available, []);
    const socket = TestSocket.sockets[0];
    socket.open();
    await jest.advanceTimersByTimeAsync(0);
    const requestsWhileConnected = getSeats.mock.calls.length;
    socket.sendUpdate("HELD");
    expect(onSeats).toHaveBeenLastCalledWith(held, available);
    const updateCount = onSeats.mock.calls.length;
    socket.sendUpdate("HELD");
    expect(onSeats).toHaveBeenCalledTimes(updateCount);
    await jest.advanceTimersByTimeAsync(3_000);
    expect(getSeats).toHaveBeenCalledTimes(requestsWhileConnected);

    socket.close();
    await jest.advanceTimersByTimeAsync(3_000);
    expect(onSeats).toHaveBeenLastCalledWith(available, available);
    expect(TestSocket.sockets).toHaveLength(2);
  } finally {
    observer.stop();
  }
  const reads = getSeats.mock.calls.length;
  await jest.advanceTimersByTimeAsync(6_000);
  expect(getSeats).toHaveBeenCalledTimes(reads);
  expect(TestSocket.sockets[1].readyState).toBe(TestSocket.CLOSED);
});

test("an older HTTP snapshot cannot overwrite a newer WebSocket frame", async () => {
  getSeats.mockResolvedValue(available);
  const onSeats = jest.fn();
  const observer = observeFlightSeats("flight-204", onSeats, jest.fn());
  try {
    await jest.advanceTimersByTimeAsync(0);
    let finish!: (snapshot: FlightSeat[]) => void;
    getSeats
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue(held);
    const socket = TestSocket.sockets[0];
    socket.open();
    socket.sendUpdate("HELD");
    expect(onSeats).toHaveBeenLastCalledWith(held, available);
    onSeats.mockClear();
    finish(available);
    await jest.advanceTimersByTimeAsync(0);
    expect(onSeats.mock.calls).toEqual([[held, held]]);
  } finally {
    observer.stop();
  }
});
