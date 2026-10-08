import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Where `npm run dev` sends /api. Defaults to the backend's own default port,
// so nothing changes unless VITE_API_TARGET is set - which is what lets a
// second copy of the API run alongside one already holding 8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8000';

  return {
  base: '/static/',
  plugins: [react()],
  build: {
    // app/static is what main.py actually serves (see tools/sync_public.py);
    // public/ is a generated deploy-copy for Vercel, regenerated from here via
    // `python tools/sync_public.py`, not written to directly by this build.
    outDir: path.resolve(__dirname, '../app/static'),
    emptyOutDir: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        // Ingesting a DSR workbook is ~2,600 rows written to a database a
        // round trip away and takes about 90 seconds. The proxy's default is
        // 60, so it returned 502 at the one-minute mark while the backend
        // carried on and finished the load - the upload appeared to fail every
        // time despite succeeding server-side. Both values are needed:
        // `timeout` bounds the incoming socket, `proxyTimeout` the outgoing one.
        timeout: 300000,
        proxyTimeout: 300000,
      },
      '/agent': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/health': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  };
});
