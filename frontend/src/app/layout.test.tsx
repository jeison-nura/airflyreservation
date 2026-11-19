import { expect, test } from "@jest/globals";
import { renderToStaticMarkup } from "react-dom/server";
import RootLayout from "./layout";

test("declares Spanish and renders the page content inside the document body", () => {
  const markup = renderToStaticMarkup(<RootLayout><main>Contenido de prueba</main></RootLayout>);
  expect(markup).toContain('<html lang="es">');
  expect(markup).toContain("<body><main>Contenido de prueba</main></body>");
});
