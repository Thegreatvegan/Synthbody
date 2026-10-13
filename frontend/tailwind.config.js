/**
 * SYNTHBODY design tokens.
 *
 * The palette is a restrained dark neutral set with a single teal accent. The
 * goal is the look of professional engineering software: high information
 * density, flat surfaces separated by hairline borders, and colour reserved for
 * meaning (series identity, evidence origin, severity) rather than decoration.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces, darkest to lightest
        void: "#07090b",
        base: "#0b0e11",
        surface: "#101418",
        panel: "#151a1f",
        raised: "#1b2127",
        hover: "#222a31",
        active: "#2a333c",

        // Hairlines
        line: "#232a31",
        "line-strong": "#313b45",

        // Text
        ink: "#e6eaee",
        "ink-dim": "#9aa6b1",
        "ink-faint": "#67727c",
        "ink-ghost": "#49525b",

        // Accent + semantics
        accent: "#3fd3bd",
        "accent-dim": "#2a9c8c",
        "accent-wash": "#0e2b28",
        info: "#5aa9e6",
        warn: "#e0a34a",
        danger: "#e2655f",
        ok: "#6bc777",
        violet: "#a98bdc",

        // Evidence-origin colour coding, used consistently everywhere
        "origin-measured": "#6bc777",
        "origin-fitted": "#3fd3bd",
        "origin-literature": "#5aa9e6",
        "origin-derived": "#a98bdc",
        "origin-inferred": "#e0a34a",
        "origin-illustrative": "#e2655f",
        "origin-user": "#9aa6b1",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "ui-monospace",
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["10px", { lineHeight: "14px", letterSpacing: "0.02em" }],
        xs: ["11px", { lineHeight: "15px" }],
        sm: ["12px", { lineHeight: "17px" }],
        base: ["13px", { lineHeight: "19px" }],
        md: ["14px", { lineHeight: "20px" }],
        lg: ["16px", { lineHeight: "23px" }],
        xl: ["19px", { lineHeight: "26px" }],
      },
      spacing: {
        "0.5": "2px",
        "1.5": "6px",
        "2.5": "10px",
        "3.5": "14px",
      },
      borderRadius: {
        xs: "2px",
        sm: "3px",
        DEFAULT: "4px",
        md: "5px",
        lg: "7px",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.025) inset",
        float: "0 12px 32px -8px rgba(0,0,0,0.75), 0 0 0 1px rgba(49,59,69,0.9)",
        focus: "0 0 0 1px #3fd3bd",
      },
      transitionDuration: { 120: "120ms", 180: "180ms" },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        sweep: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(400%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 120ms ease-out",
        "slide-up": "slide-up 150ms cubic-bezier(0.22,1,0.36,1)",
        "pulse-soft": "pulse-soft 1.4s ease-in-out infinite",
        sweep: "sweep 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
