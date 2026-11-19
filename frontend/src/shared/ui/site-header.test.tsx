/** @jest-environment jsdom */

import { afterEach, expect, test } from "@jest/globals";
import { cleanup, render, screen, within } from "@testing-library/react";
import { SiteHeader } from "./site-header";

afterEach(() => cleanup());

test("navigates to the home sections and marks Estadísticas only on its own page", () => {
  const { rerender } = render(<SiteHeader />);
  const navigation = within(screen.getByRole("navigation", { name: "Navegación principal" }));
  expect(navigation.getByRole("link", { name: "Vuelos" }).getAttribute("href")).toBe("/#buscar");
  expect(navigation.getByRole("link", { name: "Cómo funciona" }).getAttribute("href")).toBe("/#beneficios");
  const statistics = navigation.getByRole("link", { name: "Estadísticas" });
  expect(statistics.getAttribute("href")).toBe("/estadisticas");
  expect(statistics.getAttribute("aria-current")).toBeNull();
  rerender(<SiteHeader current="statistics" />);
  expect(statistics.getAttribute("aria-current")).toBe("page");
});
