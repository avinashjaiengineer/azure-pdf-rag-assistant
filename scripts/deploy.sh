#!/usr/bin/env bash
# Manually roll both container apps to an image tag already in ACR.
# Normally the GitHub Actions `deploy` job does this on every push to main; infrastructure
# itself (apps, identity, roles, env vars) is owned by Terraform in infrastructure/terraform.
#
# Usage:  bash scripts/deploy.sh               # tag = current git commit
#         TAG=<commit-sha> bash scripts/deploy.sh   # e.g. roll back to an earlier build
set -euo pipefail
export MSYS_NO_PATHCONV=1 # stop Git Bash rewriting /subscriptions/... paths

RG=${RG:-rg-pdf-rag-dev}
ACR=${ACR:-acrpdfrag487f}
TAG=${TAG:-$(git rev-parse HEAD)}

for app in api ui; do
  if ! az acr manifest show -r "$ACR" -n "pdf-rag-$app:$TAG" -o none >/dev/null 2>&1; then
    echo "pdf-rag-$app:$TAG not in $ACR. Push the commit and wait for the build workflow." >&2
    exit 1
  fi
done

for app in api ui; do
  echo "Rolling ca-pdfrag-$app -> $TAG"
  az containerapp update -n "ca-pdfrag-$app" -g "$RG" --image "$ACR.azurecr.io/pdf-rag-$app:$TAG" -o none
done
echo "UI: https://$(az containerapp show -n ca-pdfrag-ui -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
