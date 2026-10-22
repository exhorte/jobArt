import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Composition signature : contenu 3/5 à gauche, panneau sombre 2/5 à droite.
 *
 * - `grid-cols-1` explicite sous `lg` : sans lui, la colonne implicite s'élargit
 *   au contenu `nowrap` et fait déborder la page sur mobile.
 * - `min-w-0` sur chaque colonne : permet aux textes tronqués de rétrécir.
 * - `stickyAside` : le panneau reste visible pendant le défilement d'un long
 *   formulaire (aperçu en direct). `top-24` = barre supérieure (4rem) + respiration.
 * - `asideFirstOnMobile` : sur mobile, les chiffres clés passent AVANT le détail
 *   (page de résultats) ; sur desktop l'ordre naturel est conservé.
 *
 * Exemples :
 *   tableau de bord  → main = PageHeader + carte de travail ; aside = HighlightBar + MetricPanel
 *   formulaire       → main = sections du formulaire ; aside = aperçu en direct (stickyAside)
 *   résultats        → main = détails ; aside = indicateurs (stickyAside + asideFirstOnMobile)
 */
export function SplitLayout({
  main,
  aside,
  stickyAside = false,
  asideFirstOnMobile = false,
  className,
}: {
  main: ReactNode;
  aside: ReactNode;
  stickyAside?: boolean;
  asideFirstOnMobile?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-1 items-start gap-6 lg:grid-cols-5", className)}>
      <div className="flex min-w-0 flex-col gap-4 lg:col-span-3">{main}</div>
      <div
        className={cn(
          "flex min-w-0 flex-col gap-4 lg:col-span-2",
          stickyAside && "lg:sticky lg:top-24",
          asideFirstOnMobile && "order-first lg:order-none"
        )}
      >
        {aside}
      </div>
    </div>
  );
}
