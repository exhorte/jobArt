import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * État vide illustré : grande icône au trait fin entourée d'étoiles à
 * 4 branches, action (bouton bordé) et phrase d'aide. Reprend le motif
 * « Connect Wallet » des dashboards sans illustration à licencier.
 */
export function EmptyState({
  icon: Icon,
  action,
  hint,
  className,
}: {
  icon: LucideIcon;
  /** Généralement `<Button variant="outline" size="lg">…</Button>` ou un déclencheur de dialogue. */
  action: ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <Card className={cn("items-center gap-0 px-6 py-14 text-center", className)}>
      <div className="relative flex size-28 items-center justify-center">
        <Sparkle className="absolute top-1 left-2 size-4" />
        <Sparkle className="absolute top-0 right-3 size-3" />
        <Sparkle className="absolute right-0 bottom-5 size-3.5" />
        <Sparkle className="absolute bottom-2 left-4 size-2.5" />
        <Icon className="size-14 stroke-[1.25]" />
      </div>
      <div className="mt-6">{action}</div>
      {hint && <p className="mt-3 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

/** Étoile décorative à 4 branches. */
export function Sparkle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("fill-muted-foreground/25", className)} aria-hidden="true">
      <path d="M12 0c.6 6.4 5.6 11.4 12 12-6.4.6-11.4 5.6-12 12-.6-6.4-5.6-11.4-12-12C6.4 11.4 11.4 6.4 12 0Z" />
    </svg>
  );
}
