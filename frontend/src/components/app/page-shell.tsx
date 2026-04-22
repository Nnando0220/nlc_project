import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

type NavItem = {
  href: string;
  label: string;
  active?: boolean;
};

type PageShellProps = {
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
  navItems?: NavItem[];
};

const DEFAULT_NAV: NavItem[] = [
  { href: "/", label: "Inicio" },
  { href: "/upload", label: "Novo lote" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/reports", label: "Exportacoes" },
];

export function PageShell({
  title,
  description,
  actions,
  children,
  navItems = DEFAULT_NAV,
}: PageShellProps) {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(15,118,110,0.12),transparent_28%),radial-gradient(circle_at_top_right,rgba(180,83,9,0.1),transparent_32%),linear-gradient(180deg,hsl(var(--background))_0%,color-mix(in_oklab,hsl(var(--background))_88%,white)_100%)]">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-6 md:px-6 md:py-8">
        <header className="rounded-3xl border bg-background/90 px-5 py-5 shadow-sm backdrop-blur md:px-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-[0.28em] text-muted-foreground">
                NLC Document Intelligence
              </p>
              <div className="space-y-1">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
                  {title}
                </h1>
                <p className="max-w-3xl text-sm text-muted-foreground md:text-base">
                  {description}
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-3 lg:items-end">
              <nav className="flex flex-wrap gap-2">
                {navItems.map((item) => (
                  <Button
                    key={item.href}
                    asChild
                    size="sm"
                    variant={item.active ? "default" : "outline"}
                  >
                    <Link href={item.href}>{item.label}</Link>
                  </Button>
                ))}
              </nav>
              {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
            </div>
          </div>
        </header>

        {children}
      </div>
    </main>
  );
}
