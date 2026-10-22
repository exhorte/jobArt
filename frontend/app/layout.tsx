import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "./globals.css";

import { AppShell } from "@/components/layout/app-shell";
import { HeaderActions, HeaderStatus } from "@/components/layout/header-status";
import { ToastProvider } from "@/components/toast";

export const metadata: Metadata = {
  title: { default: "JobRadar", template: "%s · JobRadar" },
  description: "Veille personnelle des offres d'emploi : collecte, dédoublonnage et score de pertinence.",
  robots: { index: false, follow: false }, // outil personnel local
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0e10" },
  ],
};

// Appliqué avant le premier rendu (pas de flash) : préférence enregistrée, sinon préférence du système.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <ToastProvider>
        <AppShell
          headerInfo={<HeaderStatus />}
          headerActions={<HeaderActions />}
          footerNote="Application personnelle : les annonces restent la propriété des sites d'origine, chaque fiche renvoie vers sa source."
        >
          {children}
        </AppShell>
        </ToastProvider>
      </body>
    </html>
  );
}
