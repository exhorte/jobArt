import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type StatusTone = "success" | "warning" | "destructive" | "neutral";

const TONES: Record<StatusTone, { variant: "success" | "warning" | "destructive" | "outline"; dot: string; panel: string }> = {
  success: {
    variant: "success",
    dot: "bg-success",
    panel: "border-panel-success/30 bg-panel-success/15 text-panel-success",
  },
  warning: {
    variant: "warning",
    dot: "bg-warning",
    panel: "border-panel-warning/30 bg-panel-warning/15 text-panel-warning",
  },
  destructive: {
    variant: "destructive",
    dot: "bg-destructive",
    panel: "border-panel-destructive/30 bg-panel-destructive/15 text-panel-destructive",
  },
  neutral: {
    variant: "outline",
    dot: "bg-muted-foreground/50",
    panel: "border-panel-border text-panel-muted",
  },
};

/**
 * Badge d'état « doux » avec pastille. `onPanel` bascule sur les tokens
 * éclaircis prévus pour les surfaces sombres (sinon contraste insuffisant).
 */
export function StatusBadge({
  tone,
  label,
  onPanel = false,
  className,
}: {
  tone: StatusTone;
  label: string;
  onPanel?: boolean;
  className?: string;
}) {
  const t = TONES[tone];
  return (
    <Badge variant={t.variant} className={cn(onPanel && t.panel, className)}>
      <span className="size-1.5 rounded-full bg-current" />
      {label}
    </Badge>
  );
}

/** Pastille d'état pour la barre supérieure (équivalent de la « pastille d'adresse » des dashboards). */
export function StatusPill({
  tone,
  label,
  detail,
  className,
}: {
  tone: StatusTone;
  label: string;
  /** Complément en gris (ex. « 9,0/20 »). */
  detail?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "flex h-9 items-center gap-2 rounded-md border bg-muted/60 px-3 text-xs font-medium",
        className
      )}
    >
      <span className={cn("size-2 rounded-full", TONES[tone].dot)} />
      {label}
      {detail && <span className="text-muted-foreground tabular-nums">· {detail}</span>}
    </span>
  );
}
