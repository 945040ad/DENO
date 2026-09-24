# Supabase setup (hosted project)

Auth is Supabase Auth on a hosted project (ADR-003). Nothing Supabase runs locally — no Docker, no `supabase start`. Use one project for development and a separate one for production.

## 1. Keys → env vars

Dashboard → **Project Settings → API Keys**.

| Where | Variable | Value |
|---|---|---|
| `web/.env.local` | `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `web/.env.local` | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_…` (browser-safe) |
| `web/.env.local` | `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` (prod: the real origin) |
| `.env` (API) | `SUPABASE_URL` | same URL as above |
| `.env` (API) | `WEB_ORIGINS` | `http://localhost:3000` (comma-separated) |

The **secret key never goes into `web/`**: every `NEXT_PUBLIC_*` variable ships to the browser. The API needs no key at all; it verifies tokens with the project's public JWKS (`<url>/auth/v1/.well-known/jwks.json`).

Until both web variables are set, the app runs in dev mode: `/app` is open, and the auth screen shows the "Skip login for now" strip. Setting them turns enforcement on. The API is the same: `SUPABASE_URL` empty = dev user; `ENVIRONMENT=production` refuses to start without it.

## 2. Auth settings

Dashboard → **Authentication**:

- **Sign In / Providers → Email**: enabled, *Confirm email* on, minimum password length **10** (the UI enforces 10 too).
- **Sign In / Providers → Google**: enable, paste the Google OAuth client id/secret. In Google Cloud, the authorised redirect URI is `https://<project-ref>.supabase.co/auth/v1/callback`.
- **URL Configuration**:
  - Site URL: `http://localhost:3000` (prod: the real origin)
  - Redirect URLs: `http://localhost:3000/**` and the production origin `/**`. Nothing else.
- **JWT Keys**: new projects use asymmetric signing keys by default; keep that. (Legacy HS256 projects: set `SUPABASE_LEGACY_JWT_SECRET` on the API only.)
- **Emails → SMTP**: for production, configure custom SMTP (Resend/Postmark). The built-in sender is rate-limited and meant for testing.
- **Attack Protection → Captcha**: Cloudflare Turnstile before launch (needs the widget added to the auth form; planned in Phase 3).

## 3. How the flows land in the app

| Flow | Link target | Handler |
|---|---|---|
| Sign-up confirmation, OAuth, password reset (default templates, PKCE) | `/auth/callback?code=…&next=…` | `exchangeCodeForSession` → redirect to `next` |
| Token-hash email templates (optional, works across browsers) | `/auth/confirm?token_hash=…&type=…` | `verifyOtp` |
| Password reset | → `/auth/reset` | `updateUser({ password })` |
| Sign out | `POST /auth/signout` | `signOut()` → `/auth` |

To use token-hash links instead of PKCE (e.g. the user opens the email on another device), change the templates under **Emails → Templates** to `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email` (sign-up) and `…&type=recovery` (reset).

## 4. Calling the API

The browser sends `Authorization: Bearer <access_token>` (from `supabase.auth.getSession()`) to `/api/*`, which Next.js rewrites to FastAPI. FastAPI (`backend/app/auth.py`) verifies the signature, `iss`, `aud=authenticated` and `exp`, takes the algorithm from the JWK (never the token header), and uses `sub` as the owner id. Another user's project returns 404.
