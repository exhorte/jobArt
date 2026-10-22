import type { ReactNode } from "react";
import Link from "next/link";
import { type LucideIcon } from "lucide-react";

import { MAIN_NAV, type NavSection } from "@/components/layout/nav-config";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Logo, LogoMark } from "@/components/layout/logo";

/**
 * Coque de l'application : barre latérale fixe (desktop), barre supérieure (info à gauche, actions + thème à droite,
 * hamburger sur mobile), contenu centré (max-w-6xl) et pied de page. En-tête, contenu et pied partagent le même
 * conteneur centré pour que leurs bords gauches restent alignés.
 *
 * Server Component : l'état actif de la navigation est déduit de l'URL par la barre latérale (composant client).
 */
export function AppShell({
  sections = MAIN_NAV,
  headerInfo,
  headerActions,
  sidebarSlot,
  sidebarFooter,
  footerNote,
  children,
}: {
  sections?: NavSection[];
  headerInfo?: ReactNode;
  headerActions?: ReactNode;
  sidebarSlot?: ReactNode;
  sidebarFooter?: ReactNode;
  footerNote?: string;
  children: ReactNode;
}) {
  const nav = { brand: <Logo />, sections, slot: sidebarSlot, footer: sidebarFooter };

  return (
    <div className="flex min-h-svh">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
        <SidebarNav {...nav} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b bg-background/80 px-4 backdrop-blur-md sm:px-6 lg:px-10">
          <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3">
            <Link href="/" className="rounded-full lg:hidden" aria-label="Accueil">
              <LogoMark />
            </Link>
            <div className="min-w-0 flex-1 items-center">{headerInfo}</div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              {headerActions}
              <ThemeToggle />
              <MobileNav {...nav} />
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>

        <AppFooter note={footerNote} />
      </div>
    </div>
  );
}

/** Petite ligne d'information de la barre supérieure. */
export function HeaderInfo({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <p className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 truncate">{children}</span>
    </p>
  );
}

export function AppFooter({ note }: { note?: string }) {
  return (
    <footer className="border-t px-4 sm:px-6 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-1 py-5 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <p>JobRadar · usage personnel</p>
        {note && <p className="max-w-xl sm:text-right">{note}</p>}
      </div>
    </footer>
  );
}
