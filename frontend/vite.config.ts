import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Ports are configurable because 8000 and 5173 are commonly occupied by other
 * local services. Override with SYNTHBODY_API_PORT and SYNTHBODY_UI_PORT, or
 * with VITE_API_URL for a non-localhost backend.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiPort = env.SYNTHBODY_API_PORT ?? "8011";
  const uiPort = Number(env.SYNTHBODY_UI_PORT ?? "5180");
  const target = env.VITE_API_URL ?? `http://127.0.0.1:${apiPort}`;

  return {
    plugins: [react()],
    server: {
      port: uiPort,
      // Fail loudly rather than silently moving to another port, so the
      // documented URL is always the real one.
      strictPort: true,
      proxy: {
        "/api": { target, changeOrigin: true },
        "/health": { target, changeOrigin: true },
      },
    },
    preview: { port: uiPort + 1, strictPort: true, proxy: { "/api": { target, changeOrigin: true } } },
    build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 1200 },
  };
});
