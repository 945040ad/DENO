#!/usr/bin/env bash
# Free-tier deploy (docs/09 §5.4–5.5): Cloud Run API + run job + Cloud Scheduler, then Vercel web.
# Run from the repo root: bash deploy/deploy-free.sh
# Reads values from .env and web/.env.local; secrets go to Secret Manager / Vercel, never to the terminal.
set -euo pipefail
cd "$(dirname "$0")/.."

G=${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}
P=deno-gtm
R=asia-northeast1
TAG=$(git rev-parse --short HEAD)
IMAGE=$R-docker.pkg.dev/$P/deno/api:$TAG
API_SA=deno-api@$P.iam.gserviceaccount.com
SCHED_SA=deno-scheduler@$P.iam.gserviceaccount.com
SEARXNG_URL=https://deno-searxng-86239723863.asia-northeast1.run.app
VERCEL_PROJECT=${VERCEL_PROJECT:-deno-web}

val() { grep -m1 "^$1=" "${2:-.env}" | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/'; }
step() { printf '\n==> %s\n' "$*"; }

step "Image $IMAGE"
if ! $G artifacts docker images describe "$IMAGE" >/dev/null 2>&1; then
  $G builds submit . --region $R --config deploy/cloudbuild-api.yaml --substitutions _IMAGE="$IMAGE"
fi

step "Secret valkey-url"
if ! $G secrets describe valkey-url >/dev/null 2>&1; then
  printf '%s' "$(val VALKEY_URL)" | $G secrets create valkey-url --data-file=- --replication-policy=automatic
fi

ENV="ENVIRONMENT=production,LOG_JSON=true,SUPABASE_URL=$(val SUPABASE_URL),NVIDIA_NIM_BASE_URL=$(val NVIDIA_NIM_BASE_URL),SEARXNG_URL=$SEARXNG_URL,SEARXNG_GCP_AUTH=true"
SECRETS="DATABASE_URL=database-url:latest,NVIDIA_NIM_API_KEY=nim-key:latest,VALKEY_URL=valkey-url:latest,SUPABASE_SECRET_KEY=supabase-secret:latest"

step "Cloud Run Job deno-run"
if $G run jobs describe deno-run --region $R >/dev/null 2>&1; then
  $G run jobs update deno-run --image "$IMAGE" --region $R --set-env-vars "$ENV" --set-secrets "$SECRETS"
else
  $G run jobs create deno-run --image "$IMAGE" --region $R --service-account $API_SA \
    --command python --args=-m,deno_worker.run_once --max-retries 2 --task-timeout 30m --memory 1Gi \
    --set-env-vars "$ENV" --set-secrets "$SECRETS"
fi

step "Cloud Run service deno-api"
$G run deploy deno-api --image "$IMAGE" --region $R --service-account $API_SA \
  --port 8000 --allow-unauthenticated --min-instances 0 --max-instances 2 --timeout 3600 --memory 1Gi \
  --set-env-vars "$ENV,TASK_RUNNER=cloudrun_job,CLOUDRUN_JOB=projects/$P/locations/$R/jobs/deno-run,CRON_SERVICE_ACCOUNT=$SCHED_SA" \
  --set-secrets "$SECRETS"
API_URL=$($G run services describe deno-api --region $R --format 'value(status.url)')
$G run services update deno-api --region $R --update-env-vars "CRON_OIDC_AUDIENCE=$API_URL"
curl -fsS "$API_URL/readyz" && echo  # /healthz is reserved by Cloud Run's front end

step "Cloud Scheduler"
sched() { # name schedule path
  local verb=create
  $G scheduler jobs describe "$1" --location $R >/dev/null 2>&1 && verb=update
  $G scheduler jobs $verb http "$1" --location $R --schedule "$2" --http-method POST \
    --uri "$API_URL$3" --oidc-service-account-email $SCHED_SA --oidc-token-audience "$API_URL" >/dev/null
  echo "$1 ok"
}
sched deno-purge "17 3 * * *" /internal/cron/purge
sched deno-requeue "*/5 * * * *" /internal/cron/requeue

step "Vercel project $VERCEL_PROJECT"
cd web
vercel link --yes --project "$VERCEL_PROJECT" >/dev/null
venv() { # name value
  vercel env rm "$1" production --yes >/dev/null 2>&1 || true
  printf '%s' "$2" | vercel env add "$1" production >/dev/null
  echo "env $1 set"
}
venv NEXT_PUBLIC_SUPABASE_URL "$(val NEXT_PUBLIC_SUPABASE_URL .env.local)"
venv NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY "$(val NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY .env.local)"
venv BACKEND_URL "$API_URL"

DEPLOY_URL=$(vercel deploy --prod --yes)
WEB_URL="https://$(vercel inspect "$DEPLOY_URL" 2>&1 | grep -oE "[a-z0-9-]+\.vercel\.app" | grep -v -e "${DEPLOY_URL#https://}" -e "-projects\.vercel\.app" | head -1)"  # public alias, not the protected team one
echo "web: $WEB_URL"

step "Rebuild web with its public URL"
venv NEXT_PUBLIC_SITE_URL "$WEB_URL"
vercel deploy --prod --yes >/dev/null
cd ..

step "Allow the web origin on the API"
$G run services update deno-api --region $R --update-env-vars "WEB_ORIGINS=$WEB_URL,APP_URL=$WEB_URL"

printf '\nDone.\n  Web: %s\n  API: %s\n' "$WEB_URL" "$API_URL"
