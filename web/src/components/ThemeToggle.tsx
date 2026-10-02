import { useState } from "react";
import { getTheme, setTheme, type Theme } from "../theme";
import { Button } from "./ui";

/** A light/dark toggle. Reads/writes the persisted theme (theme.ts). */
export function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(() => getTheme());
  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title={theme === "dark" ? "Light theme" : "Dark theme"}
    >
      {theme === "dark" ? "☀" : "☾"}
    </Button>
  );
}
