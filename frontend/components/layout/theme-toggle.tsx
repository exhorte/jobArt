"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Bascule clair/sombre. Les deux icônes sont rendues et la classe `.dark`
 * choisit laquelle afficher : aucun état React, donc aucun écart
 * d'hydratation avec le thème appliqué par le script de `layout.tsx`.
 */
export function ThemeToggle() {
  const toggle = () => {
    const isDark = document.documentElement.classList.toggle("dark");
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch {
      // Stockage indisponible (navigation privée) : le thème reste valable pour la session.
    }
  };

  return (
    <Button variant="secondary" size="icon" onClick={toggle} aria-label="Basculer le thème clair / sombre">
      <Moon className="dark:hidden" />
      <Sun className="hidden dark:block" />
    </Button>
  );
}
