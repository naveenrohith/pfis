/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          foreground: 'hsl(var(--warning-foreground))',
        },
        danger: {
          DEFAULT: 'hsl(var(--danger))',
          foreground: 'hsl(var(--danger-foreground))',
        },
        info: {
          DEFAULT: 'hsl(var(--info))',
          foreground: 'hsl(var(--info-foreground))',
        },
        canvas: 'hsl(var(--canvas))',
        surface: {
          DEFAULT: 'hsl(var(--surface))',
          subtle: 'hsl(var(--surface-subtle))',
          strong: 'hsl(var(--surface-strong))',
        },
        ink: 'hsl(var(--ledger-ink))',
        jade: 'hsl(var(--jade))',
        coral: 'hsl(var(--coral))',
        settlement: 'hsl(var(--settlement-blue))',
        intelligence: 'hsl(var(--intelligence))',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'var(--radius-sm)',
        sm: 'calc(var(--radius-sm) - 2px)',
        xl: 'var(--radius-lg)',
      },
      fontFamily: {
        sans: ['Manrope', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        float: '0 18px 50px hsl(var(--shadow-color) / 0.12)',
        lift: '0 8px 24px hsl(var(--shadow-color) / 0.09)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'soft-pulse': {
          '0%, 100%': { opacity: '0.45' },
          '50%': { opacity: '0.85' },
        },
      },
      animation: {
        'fade-in': 'fade-in 180ms cubic-bezier(0.22, 1, 0.36, 1)',
        'soft-pulse': 'soft-pulse 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
