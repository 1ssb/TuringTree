/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load env so deployment can override base path / dev port / proxy target
  // without editing this file (containers, CI, sub-directory hosting, ...).
  const env = loadEnv(mode, process.cwd(), "");
  const devPort = Number(env.VITE_DEV_PORT ?? 5173);
  const proxyTarget = env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

  return {
    plugins: [react()],
    // Vitest unit-test config (jsdom + Testing Library). Runs via `npm test`.
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
      css: false,
    },
    // Public base path. Override with VITE_BASE (e.g. "/ragindex/") when the app
    // is served from a sub-directory instead of the domain root.
    base: env.VITE_BASE ?? "/",
    resolve: {
      alias: {
        // "@/..." -> "src/..."  (matches the paths alias in tsconfig.json)
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: devPort,
      // Proxy API calls to the FastAPI backend so the frontend can use same-origin
      // "/api/..." paths (no CORS juggling) in development.
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      // Surface a regression that accidentally re-bundles a heavy lib.
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          // Group heavy, route-specific libraries into their own chunks. Combined
          // with the route-level React.lazy() split, the landing page never has to
          // download the WebGL (ogl) or markdown code — those load on demand with
          // the /upload and /chat routes.
          manualChunks: {
            "vendor-react": ["react", "react-dom", "react-router-dom"],
            "vendor-webgl": ["ogl"],
            "vendor-markdown": ["react-markdown", "remark-gfm"],
          },
        },
      },
    },
  };
});
