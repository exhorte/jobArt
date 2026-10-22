import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Image Docker minimale (`node server.js`) ; sans effet en développement.
  output: "standalone",
  // L'API est jointe via le proxy `app/api/[...path]/route.ts` (BACKEND_URL lu à l'exécution, pas à la compilation).
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
