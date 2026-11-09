import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API (python -m harness.api serve on 8765); the build lands in
// web/dist, which create_app serves at / (M8 plan §1).
export default defineConfig({
  plugins: [react()],
  server: { fs: { allow: [".."] }, proxy: { "/api": "http://127.0.0.1:8765", "/healthz": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", emptyOutDir: true },
  test: { environment: "node" },
});
