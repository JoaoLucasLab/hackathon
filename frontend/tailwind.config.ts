import type { Config } from "tailwindcss";

// Tokens from frontend.md. Components use these names, never raw hex values.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        surface: "var(--surface)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        line: "var(--line)",
        "line-soft": "var(--line-soft)",
        field: "var(--field)",
        halo: "var(--halo)",
        perf: "var(--perf)",
        warn: "var(--warn)",
        star: "var(--star)",
        "sq-sage": "var(--sq-sage)",
        "sq-clay": "var(--sq-clay)",
        "sq-sky": "var(--sq-sky)",
        "sq-sea": "var(--sq-sea)",
        "sq-butter": "var(--sq-butter)",
        "sq-lilac": "var(--sq-lilac)",
        "sq-stone": "var(--sq-stone)",
      },
      fontFamily: {
        serif: ["Newsreader", "Georgia", "serif"],
        sans: ["Geist", "system-ui", "-apple-system", "sans-serif"],
      },
      maxWidth: { content: "880px", grid: "1120px" },
      borderRadius: { card: "16px", nav: "14px", btn: "9px", tag: "7px" },
    },
  },
  plugins: [],
} satisfies Config;
