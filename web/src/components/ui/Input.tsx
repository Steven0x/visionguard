import { forwardRef, useId, type InputHTMLAttributes } from "react";
import { cn } from "./cn";

export const CONTROL =
  "block w-full rounded-md border-0 bg-surface text-sm text-fg shadow-sm ring-1 ring-inset " +
  "ring-line placeholder:text-fg-muted/60 focus:ring-2 focus:ring-inset focus:ring-focus " +
  "disabled:opacity-50";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** When set, renders a <label> wired to the input (accessibility). Otherwise pass aria-label. */
  label?: string;
}

/** Text input. Always labelled: either via `label` (renders a <label htmlFor>) or an aria-label
 * passed through props. */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, id, className, ...props },
  ref,
) {
  const generated = useId();
  const inputId = id ?? generated;
  const field = (
    <input ref={ref} id={inputId} className={cn(CONTROL, "px-2.5 py-1.5", className)} {...props} />
  );
  if (!label) return field;
  return (
    <div className="space-y-1">
      <label htmlFor={inputId} className="block text-xs font-medium text-fg-muted">
        {label}
      </label>
      {field}
    </div>
  );
});
