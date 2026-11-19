import type { ReactNode } from "react";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AeroAndes | Encuentra tu próximo vuelo",
  description:
    "Compara vuelos y encuentra el horario ideal para tu próximo viaje.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
