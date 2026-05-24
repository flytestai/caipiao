/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      boxShadow: {
        glow: "0 12px 40px rgba(245, 158, 11, 0.18)",
      },
    },
  },
  plugins: [],
};
