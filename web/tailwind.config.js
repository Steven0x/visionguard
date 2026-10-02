/** @type {import('tailwindcss').Config} */
// Slice 14 design system — "Clarity" direction. Semantic colors are driven by CSS variables
// (see src/index.css :root / .dark) so a single `dark` class on <html> re-themes everything.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Inter if the OS/browser has it, otherwise the native system sans — no webfont fetch.
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          muted: "rgb(var(--surface-muted) / <alpha-value>)",
        },
        line: "rgb(var(--border) / <alpha-value>)",
        fg: {
          DEFAULT: "rgb(var(--fg) / <alpha-value>)",
          muted: "rgb(var(--fg-muted) / <alpha-value>)",
        },
        primary: {
          DEFAULT: "rgb(var(--primary) / <alpha-value>)",
          hover: "rgb(var(--primary-hover) / <alpha-value>)",
          fg: "rgb(var(--primary-fg) / <alpha-value>)",
        },
        focus: "rgb(var(--ring) / <alpha-value>)",
      },
      borderRadius: {
        DEFAULT: "0.5rem",
        md: "0.375rem",
        lg: "0.5rem",
        xl: "0.75rem",
      },
      boxShadow: {
        card: "0 1px 2px rgb(16 24 40 / 0.06), 0 1px 3px rgb(16 24 40 / 0.10)",
        pop: "0 10px 15px -3px rgb(16 24 40 / 0.12), 0 4px 6px -4px rgb(16 24 40 / 0.10)",
      },
    },
  },
  plugins: [],
};
