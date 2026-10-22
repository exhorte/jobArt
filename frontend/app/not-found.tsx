import Link from "next/link";
import { SearchX } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <EmptyState
      icon={SearchX}
      action={
        <Button asChild variant="outline" size="lg">
          <Link href="/">Retour au tableau de bord</Link>
        </Button>
      }
      hint="Cette page n'existe pas."
    />
  );
}
