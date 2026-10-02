import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** A centered dialog with an overlay. Esc and overlay-click close it; Tab is trapped inside.
 * Used in place of window.prompt/window.confirm so dialogs don't freeze the UI or look native. */
export function Modal({ open, onClose, title, children, footer }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    // Remember what was focused so we can restore it when the dialog closes (a11y).
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const nodes = ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (!nodes || nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-slate-900/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        onKeyDown={trap}
        className="relative z-10 w-full max-w-md rounded-xl bg-surface shadow-pop ring-1 ring-line focus:outline-none"
      >
        {title && (
          <div className="border-b border-line px-4 py-3 text-sm font-semibold text-fg">
            {title}
          </div>
        )}
        <div className="px-4 py-4 text-sm text-fg">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>
        )}
      </div>
    </div>
  );
}
