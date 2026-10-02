import type { ReactNode } from "react";
import { cn } from "./cn";

export type Tone = "gray" | "blue" | "indigo" | "green" | "amber" | "orange" | "red" | "teal";

export const TONES: Record<Tone, string> = {
  gray: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  blue: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  indigo: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
  green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  orange: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  teal: "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
};

export interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
  "data-testid"?: string;
}

/** A small pill. For case statuses use StatusBadge (the one status→tone source of truth). */
export function Badge({ tone = "gray", children, className, title, ...rest }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
