"use client";

import { TriangleAlert } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";

/** Erreur inattendue d'affichage (les erreurs d'API sont gérées page par page avec « Réessayer »). */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <EmptyState
      icon={TriangleAlert}
      action={
        <Button variant="outline" size="lg" onClick={reset}>
          Réessayer
        </Button>
      }
      hint={`Une erreur d'affichage est survenue${error.digest ? ` (réf. ${error.digest})` : ""}. Rechargez la page ; si elle persiste, consultez les journaux du frontend.`}
    />
  );
}
