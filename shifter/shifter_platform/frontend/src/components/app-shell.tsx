import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import {
  Bot,
  Boxes,
  CircleDollarSign,
  FileCode,
  Flag,
  HelpCircle,
  Home,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Moon,
  Server,
  Settings,
  Shield,
  ShieldAlert,
  Sun,
  Terminal,
  Trophy,
  UserCog,
  Users,
} from "lucide-react";

import { useBootstrapContext } from "@/app/bootstrap-context";
import { useMode } from "@/app/mode";
import { visibleNavGroups, type NavEntry, type NavIconKey, type UxMode } from "@/app/nav";
import { getCsrfToken } from "@/api/csrf";
import { ShifterMark } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { toggleTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const ICONS: Record<NavIconKey, ComponentType<{ className?: string }>> = {
  home: Home,
  "layout-dashboard": LayoutDashboard,
  flag: Flag,
  server: Server,
  trophy: Trophy,
  users: Users,
  "help-circle": HelpCircle,
  boxes: Boxes,
  bot: Bot,
  shield: Shield,
  "key-round": KeyRound,
  terminal: Terminal,
  settings: Settings,
  "file-code": FileCode,
  "shield-alert": ShieldAlert,
  "user-cog": UserCog,
  "circle-dollar-sign": CircleDollarSign,
};

const MODE_LABELS: Record<UxMode, string> = {
  participant: "Participate",
  operator: "Operate",
};

function NavIcon({ iconKey }: Readonly<{ iconKey: NavIconKey }>) {
  const Icon = ICONS[iconKey];
  return <Icon className="size-4" />;
}

function isActive(pathname: string, entry: NavEntry): boolean {
  // Only in-SPA entries can be "current"; external legacy links never match.
  if (entry.external) return false;
  if (entry.routePath === "/") return pathname === "/";
  return pathname === entry.routePath || pathname.startsWith(`${entry.routePath}/`);
}

function NavLink({ entry }: Readonly<{ entry: NavEntry }>) {
  const location = useLocation();
  const active = isActive(location.pathname, entry);
  const className = cn(
    "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
    active
      ? "bg-accent text-accent-foreground"
      : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
  );

  if (entry.external) {
    // Full-page navigation to the legacy Django route until the surface is
    // migrated to the SPA (route-ownership seam).
    return (
      <a href={entry.routePath} className={className}>
        <NavIcon iconKey={entry.iconKey} />
        {entry.surface}
      </a>
    );
  }
  return (
    <Link to={entry.routePath} aria-current={active ? "page" : undefined} className={className}>
      <NavIcon iconKey={entry.iconKey} />
      {entry.surface}
    </Link>
  );
}

function NavItem({ entry }: Readonly<{ entry: NavEntry }>) {
  if (entry.children && entry.children.length > 0) {
    return (
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-2.5 px-2 py-1.5 text-sm text-foreground/80">
          <NavIcon iconKey={entry.iconKey} />
          {entry.surface}
        </span>
        <div className="ml-3 flex flex-col gap-0.5 border-l border-white/10 pl-2">
          {entry.children.map((child) => (
            <NavLink key={child.surface} entry={child} />
          ))}
        </div>
      </div>
    );
  }
  return <NavLink entry={entry} />;
}

function ModeSwitch() {
  const { mode, canSwitch, setMode } = useMode();
  if (!canSwitch) return null;
  const modes: UxMode[] = ["operator", "participant"];
  return (
    <fieldset className="inline-flex rounded-md border border-white/10 bg-white/[0.03] p-0.5">
      <legend className="sr-only">Mode</legend>
      {modes.map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          onClick={() => setMode(m)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium transition-colors",
            mode === m ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {MODE_LABELS[m]}
        </button>
      ))}
    </fieldset>
  );
}

function LogoutForm() {
  // Django ``logout_view`` is POST-only; submit a same-origin form with the
  // CSRF token from the primed cookie. Auth stays server/provider-driven.
  return (
    <form method="post" action="/logout/">
      <input type="hidden" name="csrfmiddlewaretoken" value={getCsrfToken()} />
      <Button type="submit" variant="ghost" size="sm" className="gap-1.5">
        <LogOut className="size-4" />
        <span className="hidden sm:inline">Log out</span>
      </Button>
    </form>
  );
}

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const bootstrap = useBootstrapContext();
  const { mode } = useMode();
  const location = useLocation();
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const groups = visibleNavGroups(mode, bootstrap);

  // Route-change focus management (AA): move focus to the main region on
  // navigation so keyboard and screen-reader users land in the new content,
  // skipping the initial mount so the skip link keeps first focus.
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <div className="flex min-h-dvh">
        <aside
          className="hidden w-60 shrink-0 flex-col border-r border-white/10 bg-white/[0.02] px-3 py-5 backdrop-blur-xl md:flex"
          aria-label="Sidebar"
        >
          <div className="flex items-center gap-2 px-2 pb-8">
            <div className="flex size-7 items-center justify-center rounded-md border border-white/10 bg-white/[0.05]">
              <ShifterMark className="size-5" />
            </div>
            <span className="text-sm font-semibold tracking-tight">Shifter</span>
          </div>
          <nav className="flex flex-col gap-6" aria-label="Primary">
            {groups.map((group) => (
              <div key={group.group} className="flex flex-col gap-1">
                <span className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {group.group}
                </span>
                {group.entries.map((entry) => (
                  <NavItem key={entry.surface} entry={entry} />
                ))}
              </div>
            ))}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-white/10 bg-background/70 px-4 backdrop-blur-xl md:px-8">
            <span className="text-sm font-semibold md:hidden">Shifter</span>
            <ModeSwitch />
            <div className="flex-1" />
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {bootstrap.principal.display_name}
            </span>
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
            <LogoutForm />
          </header>
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 outline-none md:px-8"
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
