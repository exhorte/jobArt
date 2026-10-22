"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Saisie de liste de termes : Entrée ou virgule ajoute, Retour arrière retire le dernier, chaque terme a son bouton
 * de suppression. Les doublons (casse ignorée) sont écartés.
 */
export function TagInput({
  id,
  value,
  onChange,
  placeholder,
  transform,
  disabled,
  label,
}: {
  id: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  transform?: (s: string) => string;
  disabled?: boolean;
  label: string;
}) {
  const [draft, setDraft] = useState("");

  function commit(raw: string) {
    const parts = raw
      .split(/[,;\n]/)
      .map((p) => (transform ? transform(p.trim()) : p.trim()))
      .filter(Boolean);
    if (!parts.length) return;
    const seen = new Set(value.map((v) => v.toLowerCase()));
    const next = [...value];
    for (const p of parts) {
      if (!seen.has(p.toLowerCase())) {
        seen.add(p.toLowerCase());
        next.push(p);
      }
    }
    onChange(next);
    setDraft("");
  }

  return (
    <div
      className={cn(
        "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1.5 shadow-xs transition-[box-shadow,border-color]",
        "focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/25",
        disabled && "opacity-50",
      )}
    >
      {value.map((tag) => (
        <span key={tag} className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs font-medium">
          <span className="min-w-0 truncate">{tag}</span>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(value.filter((v) => v !== tag))}
            className="rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
            aria-label={`Retirer « ${tag} » (${label})`}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value;
          if (/[,;]/.test(v)) commit(v);
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => commit(draft)}
        placeholder={value.length ? undefined : placeholder}
        className="h-6 min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground/80"
      />
    </div>
  );
}
