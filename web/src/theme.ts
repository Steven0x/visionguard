/** Light/dark theme, persisted in localStorage and applied as a `dark` class on <html>
 * (Tailwind darkMode: "class"). Call initTheme() once at boot. */
export type Theme = "light" | "dark";

const KEY = "vg_theme";

export function getTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
  applyTheme(theme);
}

export function initTheme(): void {
  applyTheme(getTheme());
}
