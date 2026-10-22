import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Tableau à en-tête sombre : le conteneur arrondi (bordure + overflow) rogne
 * les coins de l'en-tête, ce que `border-radius` sur des cellules ne garantit
 * pas avec `border-collapse: collapse`. La bande sombre peinte sur <table>
 * (hauteur d'une ligne d'en-tête) masque les fines jointures claires que le
 * navigateur laisse entre cellules aux positions fractionnaires.
 */
function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto rounded-xl border bg-card"
    >
      <table
        data-slot="table"
        className={cn(
          "w-full caption-bottom text-sm",
          "bg-[linear-gradient(hsl(var(--panel)),hsl(var(--panel)))] bg-[length:100%_2.75rem] bg-top bg-no-repeat",
          className
        )}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("bg-panel text-panel-foreground [&_tr]:border-0 [&_tr]:hover:bg-transparent", className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn("hover:bg-muted/50 border-b transition-colors", className)}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-11 px-4 text-left align-middle text-xs font-medium whitespace-nowrap text-panel-foreground/85",
        className
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn("px-4 py-3.5 align-middle whitespace-nowrap", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell };
