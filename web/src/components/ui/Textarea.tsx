import { forwardRef, useId, type TextareaHTMLAttributes } from "react";
import { CONTROL } from "./Input";
import { cn } from "./cn";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, id, className, ...props },
  ref,
) {
  const generated = useId();
  const textareaId = id ?? generated;
  const field = (
    <textarea ref={ref} id={textareaId} className={cn(CONTROL, "px-2.5 py-1.5", className)} {...props} />
  );
  if (!label) return field;
  return (
    <div className="space-y-1">
      <label htmlFor={textareaId} className="block text-xs font-medium text-fg-muted">
        {label}
      </label>
      {field}
    </div>
  );
});
