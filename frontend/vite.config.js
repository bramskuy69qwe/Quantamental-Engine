import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // In dev, base is '/' so HMR works normally at localhost:5173.
  // In production build, base is '/static/' so FastAPI's /static mount
  // can serve the hashed asset files without any additional server config.
  base: command === 'serve' ? '/' : '/static/',
  build: {
    outDir:     '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws':  { target: 'ws://localhost:8000', ws: true },
    },
  },
}));
