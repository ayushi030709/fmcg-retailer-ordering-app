import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Local dev/preview: the app calls "/api/..." and Vite forwards it to the FastAPI server,
// so no CORS setup or API URL is needed. Production builds set VITE_API_BASE_URL instead.
const API_TARGET = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
};
// Only for tunnelled previews (e.g. a cloud dev environment). Leave unset normally.
const allowedHosts = process.env.VITE_ALLOW_ALL_HOSTS === "true" ? true : undefined;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy, allowedHosts },
  preview: { port: 4173, proxy, allowedHosts },
  build: { target: "es2020", sourcemap: false },
});
