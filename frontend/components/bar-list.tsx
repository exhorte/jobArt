import { cn } from "@/lib/utils";

/** Répartition en barres horizontales (CSS pur, sans bibliothèque de graphiques). Valeurs réelles uniquement. */
export function BarList({ items, className }: { items: { label: string; count: number }[]; className?: string }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className={cn("flex flex-col gap-3", className)}>
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate" title={i.label}>
            {i.label}
          </span>
          <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <span className="block h-full rounded-full bg-chart-1" style={{ width: `${Math.max(3, (i.count / max) * 100)}%` }} />
          </span>
          <span className="w-10 text-right tabular-nums text-muted-foreground">{i.count}</span>
        </li>
      ))}
    </ul>
  );
}
