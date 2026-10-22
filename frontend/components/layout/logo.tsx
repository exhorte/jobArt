import { cn } from "@/lib/utils";

/**
 * Pastille de logo : anneau fin + disque plein + monogramme « jA » (marque provisoire de l'application).
 */
export function LogoMark({ className, initials = "jA" }: { className?: string; initials?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8 shrink-0", className)} aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="15.25" className="fill-background stroke-border" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="12.5" className="fill-primary" />
      <text
        x="16"
        y="16"
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-primary-foreground"
        fontSize="10"
        fontWeight="700"
        letterSpacing="-0.3"
      >
        {initials}
      </text>
    </svg>
  );
}

export function Logo({
  className,
  name = "jobArt",
  tagline = "Veille emploi",
}: {
  className?: string;
  name?: string;
  tagline?: string;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="flex flex-col leading-none">
        <span className="text-sm font-semibold tracking-tight text-foreground">{name}</span>
        {tagline && <span className="mt-1 text-[11px] font-medium text-muted-foreground">{tagline}</span>}
      </span>
    </span>
  );
}
