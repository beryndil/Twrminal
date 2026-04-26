import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  // es2022 so top-level await compiles cleanly (used by shiki WASM init in
  // src/lib/render.ts). All supported browsers already ship TLA.
  build: { target: 'es2022' },
  esbuild: { target: 'es2022' },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8787',
      '/ws': { target: 'ws://127.0.0.1:8787', ws: true }
    }
  }
});
