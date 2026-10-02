import { forwardRef, useId, type SelectHTMLAttributes } from "react";
import { CONTROL } from "./Input";
import { cn } from "./cn";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
}

/** Native select, styled to match Input. Labelled via `label` or an aria-label in props. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, id, className, children, ...props },
  ref,
) {
  const generated = useId();
  const selectId = id ?? generated;
  const field = (
    <select ref={ref} id={selectId} className={cn(CONTROL, "py-1.5 pl-2.5 pr-8", className)} {...props}>
      {children}
    </select>
  );
  if (!label) return field;
  return (
    <div className="space-y-1">
      <label htmlFor={selectId} className="block text-xs font-medium text-fg-muted">
        {label}
      </label>
      {field}
    </div>
  );
});
