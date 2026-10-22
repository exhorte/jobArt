import type { ReactNode } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  header: string;
  /** Les montants et pourcentages s'alignent à droite. */
  align?: "left" | "right";
  className?: string;
  cell: (row: T) => ReactNode;
};

/**
 * Liste principale : tableau à en-tête sombre à partir de `md`, cartes empilées
 * en dessous. Le tableau défile DANS son conteneur si besoin (cellules
 * `whitespace-nowrap`), jamais la page.
 *
 * Server Component : `cell` et `mobileCard` sont des fonctions utilisées pendant
 * le rendu serveur, pas des props envoyées à un composant client.
 */
export function DataList<T>({
  rows,
  columns,
  rowKey,
  mobileCard,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  /** Contenu d'une carte mobile (voir MobileCardHeader et MobileFields). */
  mobileCard: (row: T) => ReactNode;
}) {
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c.key} className={cn(c.align === "right" && "text-right", c.className)}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((c) => (
                  <TableCell key={c.key} className={cn(c.align === "right" && "text-right tabular-nums", c.className)}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="flex flex-col gap-3 md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="rounded-xl border bg-card p-4 shadow-xs">
            {mobileCard(row)}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Pastille ronde à initiales, en tête de ligne (équivalent du « jeton » des maquettes). */
export function Avatar({ name, className }: { name: string; className?: string }) {
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join("") || "?";
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold ring-1 ring-border",
        className
      )}
    >
      {initials}
    </span>
  );
}

/** Première ligne d'une carte mobile : avatar, titre, sous-titre et badge d'état. */
export function MobileCardHeader({
  name,
  subtitle,
  badge,
}: {
  name: string;
  subtitle?: string;
  badge?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{name}</p>
        {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {badge}
    </div>
  );
}

/** Grille libellé gris / valeur en gras d'une carte mobile (3 champs maximum recommandés). */
export function MobileFields({ fields }: { fields: { label: string; value: ReactNode }[] }) {
  return (
    <dl
      className="mt-4 grid gap-3 text-sm"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, fields.length)}, minmax(0, 1fr))` }}
    >
      {fields.map((f) => (
        <div key={f.label} className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-muted-foreground">{f.label}</dt>
          <dd className="truncate font-medium tabular-nums">{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}
