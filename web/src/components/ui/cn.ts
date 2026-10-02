/** Join class names, dropping falsy values. A tiny local helper so primitives can compose
 * conditional classes without pulling in clsx/tailwind-merge. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
