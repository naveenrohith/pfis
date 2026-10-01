import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { copyFile } from 'node:fs/promises';
import { fileURLToPath, URL } from 'node:url';

const projectRoot = fileURLToPath(new URL('.', import.meta.url));
const securityDist = fileURLToPath(new URL('./security-dist/', import.meta.url));

const exposeConsoleAtRoot = {
  name: 'security-console-root-entry',
  apply: 'build' as const,
  async closeBundle() {
    await copyFile(`${securityDist}/security.html`, `${securityDist}/index.html`);
  },
};

export default defineConfig({
  root: projectRoot,
  base: '/',
  plugins: [react(), exposeConsoleAtRoot],
  build: {
    outDir: fileURLToPath(new URL('./security-dist', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./security.html', import.meta.url)),
    },
  },
});
