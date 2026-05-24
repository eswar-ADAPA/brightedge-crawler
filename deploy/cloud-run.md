# Deploying the demo to Google Cloud Run

The service is a stateless HTTP container — Cloud Run is the cheapest and
fastest target. Same image runs on AWS App Runner, Azure Container Apps, or
Fly.io with minimal changes.

## Prerequisites

- `gcloud` CLI authenticated against a project with billing enabled
- Artifact Registry repo (or use the legacy `gcr.io`)
- Region picked (e.g. `us-central1`)

## Build + deploy (one command)

```bash
export PROJECT=your-gcp-project
export REGION=us-central1
export SERVICE=brightedge-crawler-demo

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 40 \
  --max-instances 10 \
  --timeout 30s \
  --port 8080
```

Cloud Run builds the image using Buildpacks or the included `Dockerfile`,
pushes it, and exposes a public HTTPS URL.

## Test the deployed service

```bash
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')

curl -s "$URL/healthz"
curl -s --get "$URL/classify" \
  --data-urlencode 'url=https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai' \
  | jq .
```

## Equivalent AWS deployment (App Runner)

```bash
aws apprunner create-service \
  --service-name brightedge-crawler-demo \
  --source-configuration '{
    "ImageRepository": {
      "ImageIdentifier": "<ECR_URI>:latest",
      "ImageRepositoryType": "ECR",
      "ImageConfiguration": {"Port": "8080"}
    },
    "AutoDeploymentsEnabled": false
  }' \
  --instance-configuration 'Cpu=1024,Memory=2048'
```

## Notes

- Cold start is dominated by importing `trafilatura` + `yake` (~600–900 ms).
  Setting `--min-instances 1` keeps one warm if needed.
- The container ships with no secrets and no outbound egress filtering — for
  production add VPC connector + egress allowlist (see `docs/02-design.md`).
