import type { Metadata } from "next";
import "./globals.css";
import { LanguageProvider } from "../lib/i18n";
import { AppProvider } from "../lib/app-context";

export const metadata: Metadata = {
  title: "Masar — AI Academic Advisor",
  description: "Personalized academic planning for UAEU students.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <body>
        <LanguageProvider>
          <AppProvider>{children}</AppProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
