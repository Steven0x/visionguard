import type { KeyboardEvent, ReactNode } from "react";
import { cn } from "./cn";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
}

export interface TabsProps<K extends string> {
  tabs: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  className?: string;
}

/** Accessible tab bar: role=tablist, arrow-key navigation, roving tabindex. Scrolls on narrow
 * screens (the portal on a phone). */
export function Tabs<K extends string>({ tabs, value, onChange, className }: TabsProps<K>) {
  const index = tabs.findIndex((t) => t.key === value);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const dir = e.key === "ArrowRight" ? 1 : -1;
    const next = (index + dir + tabs.length) % tabs.length;
    onChange(tabs[next].key);
  };

  return (
    <div
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn("flex gap-1 overflow-x-auto border-b border-line", className)}
    >
      {tabs.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.key)}
            className={cn(
              "-mb-px whitespace-nowrap rounded-t border-b-2 px-3 py-2 text-sm font-medium " +
                "transition-colors focus-visible:outline-none focus-visible:ring-2 " +
                "focus-visible:ring-focus",
              active
                ? "border-primary text-primary"
                : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
