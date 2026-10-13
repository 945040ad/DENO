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
| `.env` (API) | `DATABASE_URL` | **Connect → Session pooler** URI (port 5432), scheme changed to `postgresql+asyncpg://` |
| `.env` (API) | `SUPABASE_SECRET_KEY` | `sb_secret_…`, so account deletion also removes the login |

The **secret key never goes into `web/`**: every `NEXT_PUBLIC_*` variable ships to the browser. The API verifies tokens with the project's public JWKS (`<url>/auth/v1/.well-known/jwks.json`); it uses the secret key only for `DELETE /me`.

Use the session pooler, not the direct `db.<ref>.supabase.co` host, which is IPv6-only. Then create the tables once, and again after each new migration: `uv run alembic upgrade head`. Never point `TEST_DATABASE_URL` at Supabase: the integration tests drop every table, and `tests/integration/conftest.py` refuses Supabase hosts for that reason.

Until both web variables are set, the app runs in dev mode: `/app` is open, and the auth screen shows the "Skip login for now" strip. Setting them turns enforcement on. The API is the same: `SUPABASE_URL` empty = dev user; `ENVIRONMENT=production` refuses to start without it.

## 2. Auth settings

Dashboard → **Authentication**:

- **Sign In / Providers → Email**: enabled, *Confirm email* on, minimum password length **10** (the UI enforces 10 too).
- **Sign In / Providers → Google**: enable, paste the Google OAuth client id/secret. In Google Cloud, the authorised redirect URI is `https://<project-ref>.supabase.co/auth/v1/callback`.
- **URL Configuration**:
  - Site URL: `http://localhost:3000` (prod: the real origin)
  - Redirect URLs: `http://localhost:3000/**` and the production origin `/**`. Nothing else.
- **JWT Keys**: new projects use asymmetric signing keys by default; keep that. (Legacy HS256 projects: set `SUPABASE_LEGACY_JWT_SECRET` on the API only.)
- **Emails → SMTP**: **required before launch.** With *Confirm email* on, every sign-up needs an email, and the built-in sender only allows a few emails an hour. Set up custom SMTP (Resend or Postmark free tiers; verify your sending domain with SPF/DKIM), then raise **Rate Limits → emails sent per hour**.
- **Multi-Factor → TOTP (App Authenticator)**: enabled. Users enrol under Account → Security. Once a user has a verified factor, a password-only session (`aal1`) is sent to `/auth/mfa` by the web app and gets `403 mfa_required` from the API, which reads `auth.mfa_factors` directly.
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

The browser sends `Authorization: Bearer <access_token>` (from `supabase.auth.getSession()`) to `/api/*`, which Next.js rewrites to FastAPI. FastAPI (`apps/api/src/deno_api/auth.py`) verifies the signature, `iss`, `aud=authenticated` and `exp`, takes the algorithm from the JWK (never the token header), and uses `sub` as the owner id. Another user's project returns 404.
