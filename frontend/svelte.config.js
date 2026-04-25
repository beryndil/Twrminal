import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      // No SPA fallback: every route is prerendered (see +layout.ts), so
      // the fallback is redundant and would overwrite the prerendered
      // index.html with a stylesheet-less shell.
      precompress: false,
      strict: true
    })
  }
};

export default config;
