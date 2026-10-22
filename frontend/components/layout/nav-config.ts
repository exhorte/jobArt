import { Briefcase, Globe, History, LayoutDashboard, Radar, Target, type LucideIcon } from "lucide-react";

/**
 * Icônes de navigation référencées par NOM : une icône Lucide est une fonction et ne peut pas traverser la frontière
 * Server Component (AppShell) → Client Component (SidebarNav). On transmet une clé, le composant client résout l'icône.
 */
export const NAV_ICONS = {
  dashboard: LayoutDashboard,
  offers: Briefcase,
  profiles: Target,
  sources: Globe,
  runs: History,
  scheduler: Radar,
} satisfies Record<string, LucideIcon>;

export type NavIconName = keyof typeof NAV_ICONS;

export type NavItem = {
  key: string;
  label: string;
  href: string;
  icon: NavIconName;
  /** Petit texte à droite (compteur…). */
  badge?: string | number;
  /** Affiche une coche verte. */
  done?: boolean;
};

export type NavSection = {
  /** Sur-titre en petites capitales. */
  title?: string;
  subtitle?: string;
  items: NavItem[];
};

export const MAIN_NAV: NavSection[] = [
  {
    items: [
      { key: "dashboard", label: "Tableau de bord", href: "/", icon: "dashboard" },
      { key: "offers", label: "Offres", href: "/offers", icon: "offers" },
      { key: "profiles", label: "Profils de recherche", href: "/profiles", icon: "profiles" },
    ],
  },
  {
    title: "Collecte",
    items: [
      { key: "sources", label: "Sources", href: "/sources", icon: "sources" },
      { key: "runs", label: "Historique", href: "/runs", icon: "runs" },
      { key: "scheduler", label: "Veille automatique", href: "/scheduler", icon: "scheduler" },
    ],
  },
];

/** Page active d'après l'URL (la barre latérale vit dans le layout racine : l'état actif se déduit côté client). */
export function activeKeyFor(pathname: string, sections: NavSection[] = MAIN_NAV): string | undefined {
  const items = sections.flatMap((s) => s.items);
  const hit = items
    .filter((i) => (i.href === "/" ? pathname === "/" : pathname === i.href || pathname.startsWith(`${i.href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return hit?.key;
}
