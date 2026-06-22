var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
var apiTarget = (_a = process.env.VITE_BACKEND_TARGET) !== null && _a !== void 0 ? _a : "http://127.0.0.1:8011";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5180,
        host: "127.0.0.1",
        proxy: {
            "/api": {
                target: apiTarget,
                changeOrigin: true,
                timeout: 30 * 60 * 1000,
                proxyTimeout: 30 * 60 * 1000,
            },
        },
    },
});
