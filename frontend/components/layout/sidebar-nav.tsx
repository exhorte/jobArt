"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CircleCheck } from "lucide-react";

import { NAV_ICONS, activeKeyFor, type NavItem, type NavSection } from "@/components/layout/nav-config";
import { cn } from "@/lib/utils";

/** Classe d'un élément de navigation — exportée pour styler un bouton "comme un lien" (ex. déclencheur de dialogue). */
export const navItemClass = (active: boolean) =>
  cn(
    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors outline-none",
    "focus-visible:ring-[3px] focus-visible:ring-ring/40 [&_svg]:size-4 [&_svg]:shrink-0",
    active
      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-xs ring-1 ring-sidebar-border"
      : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
  );

/**
 * Contenu de la barre latérale, partagé entre la colonne fixe (desktop) et le
 * tiroir mobile. `onNavigate` ferme le tiroir après un clic sur un lien.
 *
 * Structure : rangée du logo (h-16, alignée sur la barre supérieure),
 * sections de navigation, pied (h-14, aligné sur le pied de page du contenu).
 */
export function SidebarNav({
  brand,
  sections,
  slot,
  footer,
  onNavigate,
}: {
  brand: ReactNode;
  sections: NavSection[];
  /** Contenu inséré après la première section (ex. un déclencheur « Nouveau … »). */
  slot?: ReactNode;
  /** Pied de la barre latérale (ex. formulaire de déconnexion). */
  footer?: ReactNode;
  onNavigate?: () => void;
}) {
  const activeKey = activeKeyFor(usePathname(), sections);
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 shrink-0 items-center border-b border-sidebar-border px-5">
        <Link
          href="/"
          onClick={onNavigate}
          className="rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
        >
          {brand}
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-6" aria-label="Navigation principale">
        {sections.map((section, i) => (
          <div key={section.title ?? i} className={cn(i > 0 && "mt-8")}>
            {section.title && (
              <p className="px-3 text-[11px] font-medium tracking-wider text-sidebar-foreground/70 uppercase">
                {section.title}
              </p>
            )}
            {section.subtitle && (
              <p className="mt-1.5 truncate px-3 text-sm font-medium text-foreground" title={section.subtitle}>
                {section.subtitle}
              </p>
            )}
            <ul className={cn("flex flex-col gap-1", (section.title || section.subtitle) && "mt-3")}>
              {section.items.map((item) => (
                <li key={item.key}>
                  <NavLink item={item} active={item.key === activeKey} onClick={onNavigate} />
                </li>
              ))}
              {i === 0 && slot && <li>{slot}</li>}
            </ul>
          </div>
        ))}
      </nav>

      {footer && (
        <div className="flex h-14 shrink-0 items-center border-t border-sidebar-border px-3">{footer}</div>
      )}
    </div>
  );
}

function NavLink({ item, active, onClick }: { item: NavItem; active: boolean; onClick?: () => void }) {
  const Icon = NAV_ICONS[item.icon];
  return (
    <Link
      href={item.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={navItemClass(active)}
    >
      <Icon />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.done ? (
        <CircleCheck className="text-success" aria-label="Terminé" />
      ) : item.badge != null ? (
        <span className="text-[11px] text-sidebar-foreground/60 tabular-nums">{item.badge}</span>
      ) : null}
    </Link>
  );
}
