import { expect, test } from "@jest/globals";
import { summarizeOccupancy } from "./occupancy";

test("occupancy distinguishes temporary holds, confirmed seats and blocked-off positions", () => {
  const result = summarizeOccupancy([
    { seatNumber: "1A", status: "AVAILABLE" },
    { seatNumber: "1B", status: "HELD" },
    { seatNumber: "1C", status: "BOOKED" },
    { seatNumber: "1D", status: "UNAVAILABLE" },
  ]);
  expect(result).toEqual({ AVAILABLE: 1, HELD: 1, BOOKED: 1, UNAVAILABLE: 1, capacity: 3 });
  expect(summarizeOccupancy([]).capacity).toBe(0);
});
