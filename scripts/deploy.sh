#!/usr/bin/env bash
# Phase 6: deploy API + UI images (built and pushed to ACR by .github/workflows/build.yml)
# to Azure Container Apps. Idempotent: safe to re-run; later runs just roll the apps to a new tag.
#
# Prereqs (Phases 2-4): Azure OpenAI, AI Search, Storage already exist in $RG.
# Usage:  bash scripts/deploy.sh                 # deploys images tagged with the current git commit
#         TAG=<commit-sha> bash scripts/deploy.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash rewriting /subscriptions/... paths

RG=${RG:-rg-pdf-rag-dev}
LOC=${LOC:-eastus2}
SUFFIX=${SUFFIX:-487f}
ACR=acrpdfrag$SUFFIX
AOAI=aoai-pdfrag-$SUFFIX
SEARCH=srch-pdfrag-$SUFFIX
STORAGE=stpdfrag$SUFFIX
IDENTITY=id-pdfrag-$SUFFIX
ENV=cae-pdfrag-$SUFFIX
API=ca-pdfrag-api
UI=ca-pdfrag-ui
TAG=${TAG:-$(git rev-parse HEAD)}
# Comma-separated CIDRs allowed to reach the UI; default = this machine's public IP.
ALLOWED_IPS=${ALLOWED_IPS:-$(curl -s https://api.ipify.org)/32}

cd "$(dirname "$0")/.."
log() { printf '\n== %s\n' "$*"; }
exists() { "$@" -o none >/dev/null 2>&1; }

# ---------- Identity + least-privilege roles ----------
log "Managed identity $IDENTITY"
exists az identity show -n $IDENTITY -g $RG || az identity create -n $IDENTITY -g $RG -l $LOC -o none
ID_RES=$(az identity show -n $IDENTITY -g $RG --query id -o tsv)
ID_PRINCIPAL=$(az identity show -n $IDENTITY -g $RG --query principalId -o tsv)
ID_CLIENT=$(az identity show -n $IDENTITY -g $RG --query clientId -o tsv)

grant() {  # role scope
  if [ -z "$(az role assignment list --assignee "$ID_PRINCIPAL" --role "$1" --scope "$2" --query '[0].id' -o tsv)" ]; then
    az role assignment create --assignee-object-id "$ID_PRINCIPAL" --assignee-principal-type ServicePrincipal \
      --role "$1" --scope "$2" -o none
    echo "  granted: $1"
  fi
}
grant "AcrPull" "$(az acr show -n $ACR --query id -o tsv)"
grant "Cognitive Services OpenAI User" "$(az cognitiveservices account show -n $AOAI -g $RG --query id -o tsv)"
SEARCH_ID=$(az search service show -n $SEARCH -g $RG --query id -o tsv)
grant "Search Index Data Contributor" "$SEARCH_ID"
grant "Search Service Contributor" "$SEARCH_ID"   # creates the index on first ingest
grant "Storage Blob Data Contributor" "$(az storage account show -n $STORAGE -g $RG --query id -o tsv)"

# ---------- Images (pushed by GitHub Actions; ACR Tasks are blocked on Free Trial subs) ----------
log "Checking images :$TAG"
for repo in pdf-rag-api pdf-rag-ui; do
  if ! exists az acr manifest show -r $ACR -n $repo:$TAG; then
    echo "Image $repo:$TAG not found in $ACR. Push the commit and wait for the build workflow." >&2
    exit 1
  fi
done
REGISTRY=$(az acr show -n $ACR --query loginServer -o tsv)

# ---------- Container Apps environment ----------
log "Environment $ENV"
exists az containerapp env show -n $ENV -g $RG || az containerapp env create -n $ENV -g $RG -l $LOC -o none

# ---------- API (internal ingress: only reachable from inside the environment) ----------
API_ENV=(
  AZURE_CLIENT_ID=$ID_CLIENT
  LLM_PROVIDER=azure EMBEDDING_PROVIDER=azure VECTOR_STORE=azure_search DOCUMENT_STORAGE=blob
  AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show -n $AOAI -g $RG --query properties.endpoint -o tsv)
  AZURE_SEARCH_ENDPOINT=https://$SEARCH.search.windows.net
  AZURE_STORAGE_ACCOUNT_URL=$(az storage account show -n $STORAGE -g $RG --query primaryEndpoints.blob -o tsv)
)
log "API $API"
if exists az containerapp show -n $API -g $RG; then
  az containerapp update -n $API -g $RG --image $REGISTRY/pdf-rag-api:$TAG --set-env-vars "${API_ENV[@]}" -o none
else
  az containerapp create -n $API -g $RG --environment $ENV \
    --image $REGISTRY/pdf-rag-api:$TAG --registry-server $REGISTRY --registry-identity $ID_RES \
    --user-assigned $ID_RES --ingress internal --target-port 8000 \
    --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --env-vars "${API_ENV[@]}" -o none
fi

# ---------- UI (external ingress, IP-restricted) ----------
log "UI $UI"
if exists az containerapp show -n $UI -g $RG; then
  az containerapp update -n $UI -g $RG --image $REGISTRY/pdf-rag-ui:$TAG --set-env-vars API_URL=http://$API -o none
else
  az containerapp create -n $UI -g $RG --environment $ENV \
    --image $REGISTRY/pdf-rag-ui:$TAG --registry-server $REGISTRY --registry-identity $ID_RES \
    --user-assigned $ID_RES --ingress external --target-port 8501 \
    --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 \
    --env-vars API_URL=http://$API -o none
fi

log "UI access restricted to: $ALLOWED_IPS"
IFS=',' read -ra CIDRS <<< "$ALLOWED_IPS"
for i in "${!CIDRS[@]}"; do
  az containerapp ingress access-restriction set -n $UI -g $RG --rule-name "allow-$i" \
    --ip-address "${CIDRS[$i]}" --action Allow -o none
done

log "Done"
echo "UI:  https://$(az containerapp show -n $UI -g $RG --query properties.configuration.ingress.fqdn -o tsv)"
echo "API: internal only (http://$API inside the environment)"
