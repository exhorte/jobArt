# jobArt — interface

Next.js 16 (App Router) · TypeScript · Tailwind v4 · composants shadcn/ui · Inter · Lucide. Documentation générale : [../README.md](../README.md),
architecture : [../docs/architecture.md](../docs/architecture.md).

```bash
npm install
npm run dev          # http://localhost:3000 — le proxy /api joint BACKEND_URL (défaut http://127.0.0.1:8000)
npm run typecheck && npm run lint && npm test && npm run build
```

- `app/` : pages (`/`, `/offers`, `/offers/[id]`, `/profiles`, `/sources`, `/runs`, `/scheduler`) et proxy `app/api/[...path]/route.ts`.
- `components/` : coque (`layout/`), primitives (`ui/`), composants métier (tableau d'offres, dialogues de profil et d'annonce manuelle…).
- `lib/` : client API et hook `useApi` (`api.ts`), types miroir des schémas Pydantic (`types.ts`), formats et libellés français (`format.ts`).
- Thème : jetons de couleur dans `app/globals.css` (clair et sombre) ; ne jamais coder une couleur dans une page.
- `BACKEND_URL` est lue **à l'exécution** par le proxy : une même image Docker sert tous les environnements.
- **Protection d'accès** (`proxy.ts`, `lib/basic-auth.ts`) : l'API n'a aucune authentification, donc tout site public doit définir `BASIC_AUTH_USER` et
  `BASIC_AUTH_PASSWORD` (HTTP Basic, pages et `/api/*`). Sans ces variables, l'accès reste libre en local et en Docker, mais **est refusé (503)** sur Vercel
  ou avec `REQUIRE_AUTH=1` : un déploiement public ne s'ouvre jamais par oubli de configuration. Préférer un mot de passe sans caractères accentués.

> Ce projet utilise une version de Next.js dont les conventions diffèrent de celles couramment connues : consulter `node_modules/next/dist/docs/` avant de modifier le routage ou le rendu (voir `AGENTS.md`).
