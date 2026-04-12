import { defineConfig } from 'vite';
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'path';

export default defineConfig({
  plugins: [
    svelte({
      preprocess: vitePreprocess(),
      compilerOptions: {
        dev: process.env.NODE_ENV !== 'production',
      },
    }),
  ],
  resolve: {
    alias: {
      $lib: resolve('./src/lib'),
    },
  },
  clearScreen: false,
  server: {
    host: '0.0.0.0',
    port: 1420,
    strictPort: false,
    watch: {
      ignored: ['**/src-tauri/**', '**/sidecar/**'],
    },
  },
  build: {
    // LightningCSS breaks on Svelte virtual CSS — use esbuild
    cssMinify: 'esbuild',
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
  css: {
    devSourcemap: true,
  },
});
