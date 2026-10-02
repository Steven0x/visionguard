import type { ReactNode } from "react";
import { cn } from "./ui";

export interface NavItem {
  key: string;
  label: string;
}

export interface AppShellProps {
  /** Workspace switcher element (a <Select> built by the caller), shown in the sidebar. */
  switcher?: ReactNode;
  nav: NavItem[];
  activeNav: string;
  onNav: (key: string) => void;
  topRight?: ReactNode;
  children: ReactNode;
}

/** Staff console shell: a left sidebar (wordmark, workspace switcher, section nav) and a top bar
 * (theme toggle + user). Below md the sidebar collapses to a horizontal scroll nav so it stays
 * usable on a tablet. */
export function AppShell({ switcher, nav, activeNav, onNav, topRight, children }: AppShellProps) {
  const navButton = (item: NavItem, horizontal: boolean) => {
    const active = item.key === activeNav;
    return (
      <button
        key={item.key}
        type="button"
        aria-current={active ? "page" : undefined}
        onClick={() => onNav(item.key)}
        className={cn(
          "rounded-md text-sm font-medium transition-colors focus-visible:outline-none " +
            "focus-visible:ring-2 focus-visible:ring-focus",
          horizontal ? "whitespace-nowrap px-3 py-1.5" : "w-full px-3 py-2 text-left",
          active
            ? "bg-primary/10 text-primary"
            : "text-fg-muted hover:bg-surface-muted hover:text-fg",
        )}
      >
        {item.label}
      </button>
    );
  };

  return (
    <div className="flex min-h-screen bg-bg text-fg">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-4 border-r border-line bg-surface p-4 md:flex">
        <Wordmark />
        {switcher && <div>{switcher}</div>}
        <nav className="flex flex-col gap-1">{nav.map((i) => navButton(i, false))}</nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur">
          <div className="md:hidden">
            <Wordmark compact />
          </div>
          <div className="ml-auto flex items-center gap-2">{topRight}</div>
        </header>
        <div className="border-b border-line bg-surface px-2 md:hidden">
          <div className="flex gap-1 overflow-x-auto py-2">{nav.map((i) => navButton(i, true))}</div>
          {switcher && <div className="pb-2">{switcher}</div>}
        </div>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-fg">
        V
      </span>
      {!compact && <span className="text-base font-bold tracking-tight">VisionGuard</span>}
    </div>
  );
}
