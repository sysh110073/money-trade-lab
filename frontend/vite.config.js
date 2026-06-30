import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";

const portfolioApiPlugin = () => ({
  name: 'portfolio-api',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url === '/api/portfolio' && req.method === 'GET') {
        const file = path.resolve(__dirname, '../data/real_portfolio.json');
        if (fs.existsSync(file)) {
          res.setHeader('Content-Type', 'application/json');
          res.end(fs.readFileSync(file));
        } else {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify([]));
        }
        return;
      }
      if (req.url === '/api/portfolio' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', () => {
          const file = path.resolve(__dirname, '../data/real_portfolio.json');
          fs.writeFileSync(file, body);
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ success: true }));
        });
        return;
      }
      next();
    });
  }
});

export default defineConfig({
  plugins: [react(), portfolioApiPlugin()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    allowedHosts: [".trycloudflare.com"]
  },
  preview: {
    host: "127.0.0.1",
    port: 4173
  },
  build: {
    chunkSizeWarningLimit: 1800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) {
            return "react-vendor";
          }
          if (id.includes("node_modules/plotly.js") || id.includes("node_modules/react-plotly.js")) {
            return "plotly-vendor";
          }
          if (id.includes("node_modules")) {
            return "vendor";
          }
        }
      }
    }
  }
});
