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
        paper: "#ffffff"
      }
    }
  },
  plugins: []
};
