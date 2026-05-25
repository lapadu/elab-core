/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "../elab_clients_core/python/assets/**/*.{js,ts,jsx,tsx}",
    "../elab_clients_premium/python/assets/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      transformOrigin: {
        '3d': '50% 50% 0',
      },
    },
  },
  plugins: [
    function({ addUtilities }) {
      addUtilities({
        '.transform-style-3d': {
          transformStyle: 'preserve-3d',
        },
        '.perspective-1000': {
          perspective: '1000px',
        },
        '.rotate-y-180': {
          transform: 'rotateY(180deg)',
        },
        '.backface-hidden': {
          backfaceVisibility: 'hidden',
        },
      });
    },
  ],
}
