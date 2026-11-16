/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        obsidian: {
          950: "#060911",
          900: "#0b101d",
          800: "#121a2d",
          700: "#1c2842",
        },
      },
    },
  },
  plugins: [],
};

