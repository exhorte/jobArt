import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/** Liste déroulante native (accessible et fiable sur mobile), habillée comme `Input`. */
function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select
        data-slot="select"
        className={cn(
          "h-10 w-full min-w-0 appearance-none rounded-md border border-input bg-background pr-9 pl-3 text-sm shadow-xs transition-[color,box-shadow,border-color] outline-none",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25",
          "aria-invalid:border-destructive disabled:cursor-not-allowed disabled:opacity-50",
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
    </div>
  );
}

export { Select };
