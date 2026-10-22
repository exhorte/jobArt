import type { ReactNode } from "react";
import { Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/** Encadré d'information ("Important") ou d'avertissement. */
export function Callout({
  title,
  children,
  variant = "info",
  className,
}: {
  title: string;
  children: ReactNode;
  variant?: "info" | "warning";
  className?: string;
}) {
  const Icon = variant === "warning" ? TriangleAlert : Info;
  return (
    <div
      role={variant === "warning" ? "alert" : "note"}
      className={cn(
        "rounded-xl border p-4 sm:px-5",
        variant === "warning" && "border-warning/30 bg-warning/5",
        className
      )}
    >
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Icon className={cn("size-4 shrink-0", variant === "warning" && "text-warning")} />
        {title}
      </p>
      <div className="mt-1.5 pl-6 text-sm text-muted-foreground">{children}</div>
    </div>
  );
}
