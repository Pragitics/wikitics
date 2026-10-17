/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#384959",
        steel: "#64748b",
        mint: "#384959",
        amberline: "#88BDF2",
        accent: "#88BDF2",
        paper: "#ffffff",
        canvas: "#F5F7F9",
        hairline: "#E5E9EF",
        wash: "#EDF1F6"
      },
      fontFamily: {
        sans: ['"Geist Variable"', "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        display: ['"Instrument Serif"', "ui-serif", "Georgia", "serif"]
      }
    }
  },
  plugins: []
};
