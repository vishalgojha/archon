import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Space Grotesk'", "ui-sans-serif", "system-ui"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular"]
      },
      colors: {
        base: "var(--studio-base)",
        panel: "var(--studio-panel)",
        panelSoft: "var(--studio-panel-soft)",
        ink: "var(--studio-ink)",
        inkMuted: "var(--studio-ink-muted)",
        stroke: "var(--studio-stroke)",
        accent: "var(--studio-accent)",
        accentStrong: "var(--studio-accent-strong)",
        accentWarm: "var(--studio-accent-warm)",
        good: "var(--studio-good)",
        warn: "var(--studio-warn)",
        danger: "var(--studio-danger)"
      },
      boxShadow: {
        "glow-soft": "0 0 0 1px rgba(110, 231, 255, 0.12), 0 12px 40px rgba(6, 14, 24, 0.6)",
        "panel": "0 18px 50px rgba(4, 9, 16, 0.7)"
      }
    }
  },
  plugins: []
} satisfies Config;
