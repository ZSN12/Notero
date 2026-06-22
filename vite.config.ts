import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tsconfigPaths from "vite-tsconfig-paths";
import { traeBadgePlugin } from 'vite-plugin-trae-solo-badge';

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  build: {
    sourcemap: 'hidden',
    rollupOptions: {
      output: {
        manualChunks: {
          // Core vendor libraries that change infrequently
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // UI / styling
          'vendor-ui': ['lucide-react', 'tailwindcss'],
          // State & data
          'vendor-state': ['zustand'],
          // Visualization (large)
          'vendor-viz': ['@xyflow/react', 'elkjs'],
          // Markdown / PDF rendering (large)
          'vendor-doc': ['react-markdown', 'rehype-raw', 'rehype-katex', 'remark-gfm', 'remark-math', 'katex', 'html2pdf.js'],
        },
      },
    },
  },
  plugins: [
    react({
      babel: command === 'serve' ? {
        plugins: ['react-dev-locator'],
      } : undefined,
    }),
    traeBadgePlugin({
      variant: 'dark',
      position: 'bottom-right',
      prodOnly: true,
      clickable: true,
      clickUrl: 'https://www.trae.ai/solo?showJoin=1',
      autoTheme: true,
      autoThemeTarget: '#root'
    }),
    tsconfigPaths()
  ],
}))
