import type { ReactNode } from "react";
import { cn } from "./cn";

export interface CardProps {
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** data-testid passthrough for existing tests that query sections. */
  "data-testid"?: string;
}

/** A surface panel with an optional header (title + right-aligned actions). The body gets
 * default padding; pass bodyClassName="p-0" for flush tables/lists. */
export function Card({ title, actions, children, className, bodyClassName, ...rest }: CardProps) {
  return (
    <section
      className={cn("rounded-xl bg-surface shadow-card ring-1 ring-line", className)}
      {...rest}
    >
      {(title || actions) && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          {title && <h3 className="text-sm font-semibold text-fg">{title}</h3>}
          {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
