import { useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { Moon, ShieldAlert, Sun } from "lucide-react";

import { ShifterMark } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { toggleTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
}

const NAV_GROUPS: ReadonlyArray<{ group: string; items: NavItem[] }> = [
  { group: "Govern", items: [{ label: "Risks", to: "/", icon: <ShieldAlert className="size-4" /> }] },
];

function isActive(pathname: string, to: string): boolean {
  if (to === "/") {
    return pathname === "/" || pathname.startsWith("/risks");
  }
  return pathname.startsWith(to);
}

export function AppShell({ principalName, children }: Readonly<{ principalName: string; children: ReactNode }>) {
  const location = useLocation();
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <div className="flex min-h-dvh">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-white/10 bg-white/[0.02] px-3 py-5 backdrop-blur-xl md:flex">
          <div className="flex items-center gap-2 px-2 pb-8">
            <div className="flex size-7 items-center justify-center rounded-md border border-white/10 bg-white/[0.05]">
              <ShifterMark className="size-5" />
            </div>
            <span className="text-sm font-semibold tracking-tight">Shifter</span>
          </div>
          <nav className="flex flex-col gap-6" aria-label="Primary">
            {NAV_GROUPS.map((group) => (
              <div key={group.group} className="flex flex-col gap-1">
                <span className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {group.group}
                </span>
                {group.items.map((item) => {
                  const active = isActive(location.pathname, item.to);
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                        active
                          ? "bg-accent text-accent-foreground"
                          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                      )}
                    >
                      {item.icon}
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-white/10 bg-background/70 px-4 backdrop-blur-xl md:px-8">
            <span className="text-sm font-semibold md:hidden">Shifter</span>
            <div className="flex-1" />
            <span className="hidden text-sm text-muted-foreground sm:inline">{principalName}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle theme"
              onClick={() => {
                toggleTheme();
                setDark(document.documentElement.classList.contains("dark"));
              }}
            >
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
          </header>
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-8">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
