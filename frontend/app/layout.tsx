import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "ContextWeave — Mock Interview Practice", description: "Consent-based mock interview practice" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
