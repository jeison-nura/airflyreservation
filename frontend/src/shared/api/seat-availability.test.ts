import { expect, test } from "@jest/globals";
import { newlyOccupiedSeats, parseSeatUpdate } from "./seat-availability";

test("only seats that were available produce an occupied notice", () => {
  const original = [
    { seatNumber: "1A", status: "AVAILABLE" },
    { seatNumber: "1B", status: "HELD" },
    { seatNumber: "1C", status: "BOOKED" },
  ] as const;
  const updated = [
    { seatNumber: "1A", status: "HELD" },
    { seatNumber: "1B", status: "BOOKED" },
    { seatNumber: "1C", status: "AVAILABLE" },
  ] as const;

  expect(newlyOccupiedSeats(original, updated)).toEqual(["1A"]);
  expect(newlyOccupiedSeats(updated, updated)).toEqual([]);
  expect(newlyOccupiedSeats([], updated)).toEqual([]);
});

test("seat updates reject malformed frames and other flights", () => {
  const payload = { type: "seat.updated", flightId: "flight-204", seatNumber: "1A" };
  expect(parseSeatUpdate(JSON.stringify({ ...payload, status: "HELD" }), "flight-204")).toEqual({
    seatNumber: "1A",
    status: "HELD",
  });
  expect(parseSeatUpdate(JSON.stringify({ ...payload, status: "HELD" }), "other")).toBeNull();
  expect(parseSeatUpdate(JSON.stringify({ ...payload, status: "INVALID" }), "flight-204")).toBeNull();
  expect(parseSeatUpdate("{", "flight-204")).toBeNull();
  expect(parseSeatUpdate({ ...payload, status: "HELD" }, "flight-204")).toBeNull();
});

test("after release, a new booking can trigger the notice again", () => {
  const held = [{ seatNumber: "1A", status: "HELD" }] as const;
  const released = [{ seatNumber: "1A", status: "AVAILABLE" }] as const;
  const booked = [{ seatNumber: "1A", status: "BOOKED" }] as const;
  expect(newlyOccupiedSeats(held, released)).toEqual([]);
  expect(newlyOccupiedSeats(released, booked)).toEqual(["1A"]);
});
