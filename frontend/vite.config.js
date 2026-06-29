import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// During the migration the build emits to `dist/`. The existing FastAPI static
// dashboard remains the served default until views reach parity and the
// `/dashboard` route is pointed at the built bundle (see README.md → Cutover).
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to the FastAPI backend during local development.
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
