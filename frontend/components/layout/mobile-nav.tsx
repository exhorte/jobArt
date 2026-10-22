"use client";

import { useState, type ComponentProps } from "react";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { SidebarNav } from "@/components/layout/sidebar-nav";

/** Bouton hamburger (sous `lg`) qui ouvre la barre latérale dans un tiroir. */
export function MobileNav(props: Omit<ComponentProps<typeof SidebarNav>, "onNavigate">) {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline" size="icon" className="lg:hidden" aria-label="Ouvrir le menu">
          <Menu />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-72 gap-0 bg-sidebar p-0">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">Menu principal de l&rsquo;application.</SheetDescription>
        <SidebarNav {...props} onNavigate={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}
