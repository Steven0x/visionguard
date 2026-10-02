import type { ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** A next-action, e.g. a <Button>. Every empty state should offer one when it can. */
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

/** The empty state: what to show when a list has nothing yet, with a path forward. */
export function EmptyState({ title, description, action, icon, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed " +
          "border-line px-6 py-10 text-center",
        className,
      )}
    >
      {icon && <div className="text-fg-muted">{icon}</div>}
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && <p className="max-w-sm text-xs text-fg-muted">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
