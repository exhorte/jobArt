import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-20 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs transition-[color,box-shadow,border-color] outline-none",
        "placeholder:text-muted-foreground/80",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25",
        "aria-invalid:border-destructive disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
