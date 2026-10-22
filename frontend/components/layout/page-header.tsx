import type { ReactNode } from "react";
import { Clock, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** Grand titre de page + sous-titre précédé d'une icône (horloge par défaut). */
export function PageHeader({
  title,
  subtitle,
  icon: Icon = Clock,
  actions,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {typeof title === "string" ? (
          <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{title}</h1>
        ) : (
          title
        )}
        {subtitle && (
          <p className="mt-1.5 flex items-center gap-1.5 text-sm text-muted-foreground">
            <Icon className="size-3.5 shrink-0" />
            <span className="min-w-0">{subtitle}</span>
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
