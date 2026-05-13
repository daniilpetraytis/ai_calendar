import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e14",
        panel: "#11151c",
        border: "#1c2230",
        text: "#e6e8eb",
        muted: "#8a93a6",
        accent: "#7c5cff",
        success: "#22c55e",
        danger: "#ef4444",
        warn: "#f59e0b",
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
