"use client";

import type { ComponentProps } from "react";
import { Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useLaunchRun } from "@/lib/use-launch-run";

/** Bouton « Lancer une collecte » (toutes les sources activées). */
export function LaunchRunButton({
  children = "Lancer une collecte",
  iconOnlyOnMobile = false,
  ...props
}: Omit<ComponentProps<typeof Button>, "onClick" | "disabled"> & { iconOnlyOnMobile?: boolean }) {
  const { launch, busy } = useLaunchRun();
  return (
    <Button onClick={() => launch()} disabled={busy} aria-busy={busy} {...props}>
      {busy ? <Loader2 className="animate-spin" /> : <Play />}
      <span className={iconOnlyOnMobile ? "max-sm:sr-only" : undefined}>{children}</span>
    </Button>
  );
}
