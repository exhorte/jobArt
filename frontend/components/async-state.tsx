import type { ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Bloc d'attente discret (chargement initial uniquement : les rechargements gardent les données affichées). */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-muted/70", className)} aria-hidden="true" />;
}

export function PageSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Chargement en cours">
      <Skeleton className="h-9 w-64" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-24 w-full" />
      ))}
    </div>
  );
}

/** Erreur de chargement avec action « Réessayer ». Le message vient du backend (déjà en français). */
export function ErrorNotice({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn("flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm", className)}>
      <TriangleAlert className="size-4 shrink-0 text-destructive" aria-hidden="true" />
      <p className="min-w-0 flex-1 break-words">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw /> Réessayer
        </Button>
      )}
    </div>
  );
}

/** Rend `children` quand les données sont là ; sinon squelette ou erreur. */
export function Loadable({
  error,
  hasData,
  onRetry,
  rows,
  children,
}: {
  error: string | null;
  hasData: boolean;
  onRetry?: () => void;
  rows?: number;
  children: ReactNode;
}) {
  if (!hasData && error) return <ErrorNotice message={error} onRetry={onRetry} />;
  if (!hasData) return <PageSkeleton rows={rows} />;
  return (
    <>
      {error && <ErrorNotice message={`Actualisation impossible : ${error}`} onRetry={onRetry} className="mb-4" />}
      {children}
    </>
  );
}
