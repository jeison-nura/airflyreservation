import { expect, test } from "@jest/globals";

import {
  canGoToStep,
  isPassengerDetailsValid,
} from "./booking";

test("requires a passenger name and valid email", () => {
  expect(isPassengerDetailsValid({ fullName: " Ana Pérez ", email: " ana@example.test " })).toBe(true);
  expect(isPassengerDetailsValid({ fullName: " A ", email: "ana@example.test" })).toBe(false);
  expect(isPassengerDetailsValid({ fullName: "Ana Pérez", email: "ana@" })).toBe(false);
});

test("stepper only allows returning to an already reached step", () => {
  expect(canGoToStep(1, 3)).toBe(true);
  expect(canGoToStep(3, 3)).toBe(true);
  expect(canGoToStep(4, 3)).toBe(false);
});
