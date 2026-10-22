import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "success" | "warning" | "destructive";

const TONE_CLASS: Record<Tone, string> = {
  success: "text-panel-success",
  warning: "text-panel-warning",
  destructive: "text-panel-destructive",
};

/** Bandeau sombre compact : grande icône, valeur, libellé aligné à droite. */
export function HighlightBar({
  icon: Icon,
  value,
  label,
  aside,
  className,
}: {
  icon: LucideIcon;
  value: ReactNode;
  label: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-4 rounded-xl bg-panel px-5 py-4 text-panel-foreground shadow-sm",
        className
      )}
    >
      <Icon className="size-8 shrink-0 stroke-[1.5]" aria-hidden="true" />
      <div className="min-w-0">
        <p className="truncate text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      </div>
      <div className="ml-auto flex shrink-0 flex-col items-end gap-1.5 text-right">
        <span className="text-sm text-panel-muted">{label}</span>
        {aside}
      </div>
    </div>
  );
}

/** Panneau sombre empilant des métriques séparées par de fins filets. */
export function MetricPanel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-col divide-y divide-panel-border overflow-hidden rounded-xl bg-panel text-panel-foreground shadow-sm",
        className
      )}
    >
      {children}
    </div>
  );
}

export function MetricPanelItem({
  label,
  value,
  unit,
  hint,
  icon: Icon,
  solidIcon = false,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  icon: LucideIcon;
  /** Pastille pleine (vert menthe pâle) pour mettre en avant une métrique. */
  solidIcon?: boolean;
  tone?: Tone;
}) {
  return (
    <div className="flex items-start justify-between gap-4 p-6">
      <div className="min-w-0">
        <p className="text-sm text-panel-muted">{label}</p>
        <p
          className={cn(
            "mt-2 text-2xl font-semibold tracking-tight tabular-nums sm:text-[28px] sm:leading-9",
            tone && TONE_CLASS[tone]
          )}
        >
          {value}
          {unit && <span className="ml-1.5 text-base font-medium text-panel-foreground">{unit}</span>}
        </p>
        {hint && <p className="mt-1.5 text-xs text-panel-muted">{hint}</p>}
      </div>
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-full",
          solidIcon
            ? "bg-panel-highlight text-panel-highlight-foreground"
            : "bg-white/10 text-panel-foreground"
        )}
      >
        <Icon className="size-4" aria-hidden="true" />
      </span>
    </div>
  );
}

/** Liste clé / valeur compacte, à placer en bas d'un `MetricPanel`. */
export function MetricPanelList({
  items,
}: {
  items: { label: string; value: ReactNode }[];
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-4 p-6 text-sm">
      {items.map((item) => (
        <div key={item.label} className="flex flex-col gap-1">
          <dt className="text-xs text-panel-muted">{item.label}</dt>
          <dd className="font-medium tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
