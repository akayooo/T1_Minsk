/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'dark-primary': '#191a1a',
        'dark-secondary': '#202222',
        'dark-accent': '#202222',
        'dark-text': '#E0E0E0',
        'dark-border': '#202222',
        'dark-hover': '#343541',
        'custom-blue': '#58b5ca', 
        'custom-gray': '#444654',
        'custom-light-gray': '#565869',
        'custom-border': '#3e3f4b',
      },
      boxShadow: {
        'custom': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'custom-lg': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
      },
    },
  },
  plugins: [],
};
