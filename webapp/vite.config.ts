import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// Served by the bot's FastAPI app under /app/ (see bot/web.py).
export default defineConfig({
  base: "/app/",
  plugins: [vue()],
  server: {
    proxy: { "/api": "http://localhost:8080" },
  },
});
