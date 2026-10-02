import type { ReactNode } from "react";

/** Agency portal chrome: a clean branded header (VisionGuard wordmark + agency name) and a
 * single-column body that works on a phone. The tabs + content are passed as children. */
export function PortalShell({
  agencyName,
  email,
  topRight,
  children,
}: {
  agencyName: string;
  email: string;
  topRight?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-fg">
            V
          </span>
          <div className="min-w-0">
            <div className="text-sm font-bold leading-tight tracking-tight">VisionGuard</div>
            <div className="truncate text-xs text-fg-muted leading-tight">{agencyName}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-fg-muted sm:inline">{email}</span>
            {topRight}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-5">{children}</main>
    </div>
  );
}
