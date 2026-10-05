# Azure PDF RAG Assistant

Upload PDFs, ask questions, get answers grounded in the documents with file/page citations.
Built in phases: everything works locally first (Ollama + FAISS), then each component is
swapped for its Azure equivalent by changing configuration, not code.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Local RAG: PyPDF → chunking → Ollama embeddings → FAISS → Ollama LLM, with citations | ✅ Done |
| 2 | Azure OpenAI for chat + embeddings (`LLM_PROVIDER=azure`, `EMBEDDING_PROVIDER=azure`), Entra ID auth | ✅ Done |
| 3 | Azure AI Search with hybrid (keyword + vector) retrieval (`VECTOR_STORE=azure_search`) | ✅ Done |
| 4 | Azure Blob Storage for uploaded PDFs (`DOCUMENT_STORAGE=blob`) | ✅ Done |
| 5 | FastAPI (`/upload`, `/ingest`, `/chat`, `/documents`) + Streamlit UI | ✅ Done |
| 6 | Docker → Azure Container Registry → Azure Container Apps (scale to zero) | ⏳ |
| 7 | Terraform infrastructure + GitHub Actions CI/CD | ⏳ |

## Architecture (Phase 1)

```
PDF ─► pdf_loader ─► chunker ─► embeddings ─► vector_store (FAISS)
                    (per page)   (Ollama)          │
                                                   ▼
question ─► embed_query ─► retriever ─► top-k chunks ─► generator (Ollama) ─► answer + citations
```

Each backend sits behind a small interface (`Embedder`, `VectorStore`, `Generator`) with a
`get_*()` factory driven by `src/config/settings.py`. Later phases add implementations;
the pipeline, scripts, and tests stay the same.

## Quick start (Phase 1, fully local, $0)

Prerequisites: Python 3.12, [Ollama](https://ollama.com) running locally.

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env

# Put PDFs in data\raw\, then:
python -m scripts.ingest                  # index every PDF in storage (data\raw\ or Blob)
python -m scripts.ingest my.pdf           # upload to storage, then index
python -m scripts.ingest --list           # show indexed documents
python -m scripts.ask "What is AKS?"      # one question
python -m scripts.ask -v                  # interactive, shows retrieved chunks + scores
python -m pytest                          # tests (no Ollama needed)
```

Re-ingesting the same file replaces its chunks (document IDs are content hashes).
If you change the embedding model within a provider, delete `data\processed\faiss\<provider>\` and re-ingest.

## Phase 2: Azure OpenAI

Authentication uses `DefaultAzureCredential`: your `az login` session locally, managed identity
once deployed. Key auth is disabled on the resource, so there are no secrets to leak.

One-time setup (Azure CLI; in Git Bash prefix role commands with `MSYS_NO_PATHCONV=1`):

```bash
RG=rg-pdf-rag-dev; LOC=eastus2; NAME=aoai-pdfrag-<suffix>
az provider register -n Microsoft.CognitiveServices --wait
az group create -n $RG -l $LOC
az cognitiveservices account create -n $NAME -g $RG -l $LOC --kind OpenAI --sku S0 --custom-domain $NAME --yes
az resource update -g $RG -n $NAME --resource-type Microsoft.CognitiveServices/accounts --set properties.disableLocalAuth=true
az cognitiveservices account deployment create -g $RG -n $NAME --deployment-name gpt-5-mini   --model-name gpt-5-mini --model-version 2025-08-07 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 50
az cognitiveservices account deployment create -g $RG -n $NAME --deployment-name text-embedding-3-small   --model-name text-embedding-3-small --model-version 1 --model-format OpenAI --sku-name Standard --sku-capacity 120
az role assignment create --assignee-object-id $(az ad signed-in-user show --query id -o tsv)   --assignee-principal-type User --role "Cognitive Services OpenAI User"   --scope $(az cognitiveservices account show -g $RG -n $NAME --query id -o tsv)
```

Then set `AZURE_OPENAI_ENDPOINT`, `LLM_PROVIDER=azure`, `EMBEDDING_PROVIDER=azure` in `.env` and re-run
`python -m scripts.ingest`. Each embedding provider gets its own index under `data/processed/faiss/<provider>/`,
so you can switch back to Ollama at any time without re-ingesting.

Notes:
- `gpt-4o-mini` can no longer be newly deployed (deprecated 2026-03-31); `gpt-5-mini` is the cheap replacement.
- `gpt-5-mini` is a reasoning model: it takes `reasoning_effort` instead of `temperature`. `minimal` occasionally
  refused answerable questions in testing, so the default is `low`.
- Model deployments have no standing cost; you pay per token. The Free Trial spending limit caps spend at your credit.

## Phase 3: Azure AI Search

`VECTOR_STORE=azure_search` swaps FAISS for Azure AI Search (Free tier). Queries are **hybrid**: BM25 keyword
search plus HNSW vector search, fused with Reciprocal Rank Fusion. That's why scores look like `0.0333`
(≈ 1/61 + 1/61 for a chunk ranked first in both lists) rather than cosine similarities.

The index (`pdf-chunks-<embedding_provider>`) is created on first ingest, sized to the real embedding dimension.
Fields mirror the `Chunk` model: `id`, `document_id`, `filename`, `page_number`, `chunk_id`, `content`,
`content_vector`. The vector field is searchable but not stored, which roughly halves vector storage on the
50 MB free tier.

One-time setup (Free tier: one per subscription; if a region reports `InsufficientResourcesAvailable`, try another):

```bash
export MSYS_NO_PATHCONV=1   # Git Bash only
RG=rg-pdf-rag-dev; NAME=srch-pdfrag-<suffix>
az provider register -n Microsoft.Search --wait
az search service create -n $NAME -g $RG -l eastus --sku free   --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge
SCOPE=$(az search service show -n $NAME -g $RG --query id -o tsv)
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee-object-id $ME --assignee-principal-type User --role "Search Service Contributor" --scope $SCOPE
az role assignment create --assignee-object-id $ME --assignee-principal-type User --role "Search Index Data Contributor" --scope $SCOPE
```

Then set `AZURE_SEARCH_ENDPOINT` and `VECTOR_STORE=azure_search` in `.env` and run `python -m scripts.ingest`.

## Phase 4: Azure Blob Storage

`DOCUMENT_STORAGE=blob` keeps the original PDFs in a Blob container instead of `data/raw/`. Ingestion always
goes upload -> storage -> read back -> index, so storage holds the source of truth for everything indexed:

- `python -m scripts.ingest a.pdf` uploads `a.pdf`, then indexes it.
- `python -m scripts.ingest` re-indexes every PDF in the container (e.g. after changing chunk size).
- `python -m scripts.ingest --delete <id>` removes the chunks from the index **and** the blob.
- Uploading a changed file under the same name replaces the old version's chunks.

The storage account has shared-key access and public blob access disabled; Entra ID is the only way in.

```bash
export MSYS_NO_PATHCONV=1   # Git Bash only
RG=rg-pdf-rag-dev; SA=stpdfrag<suffix>
az provider register -n Microsoft.Storage --wait
az storage account create -n $SA -g $RG -l eastus2 --sku Standard_LRS --kind StorageV2 --access-tier Hot   --allow-blob-public-access false --allow-shared-key-access false --min-tls-version TLS1_2 --https-only true
az storage container-rm create --storage-account $SA -g $RG -n documents --public-access off
az role assignment create --assignee-object-id $(az ad signed-in-user show --query id -o tsv)   --assignee-principal-type User --role "Storage Blob Data Contributor"   --scope $(az storage account show -n $SA -g $RG --query id -o tsv)
```

Then set `AZURE_STORAGE_ACCOUNT_URL` and `DOCUMENT_STORAGE=blob` in `.env`.

Local runs spend ~1 s per Azure service fetching an `az login` token; all clients share one credential so
the chain is only probed once. Deployed with managed identity (Phase 6), token fetches are near-instant.

## Phase 5: FastAPI + Streamlit

```powershell
uvicorn src.api.main:app --reload            # API on http://localhost:8000 (docs at /docs)
streamlit run frontend/app.py                # UI on http://localhost:8501 (API_URL env to point elsewhere)
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Status + which backends are active |
| POST | `/upload` | Multipart PDF → validate → index → store. Returns `document_id`, `chunks` |
| POST | `/ingest?filename=` | Re-index one stored PDF, or all if omitted |
| POST | `/chat` | `{"question": "...", "top_k": 5}` → answer, citations, retrieved chunks |
| GET | `/documents` | Indexed documents |
| DELETE | `/documents/{id}` | Remove from index and storage |

Uploads are rejected (and never stored) if the name isn't `.pdf` (400), the bytes aren't a PDF (400), the file
exceeds `MAX_UPLOAD_MB` (413), or it can't be parsed / has no extractable text (422). The PDF is indexed before
it is stored, and the index entry is rolled back if storing fails, so index and storage stay in sync.

The UI only talks to the API over HTTP, so the two can be deployed as separate containers in Phase 6.

## Project layout

```
src/
  config/settings.py      # all settings, read from .env
  models/schemas.py       # PageText, Chunk, RetrievedChunk, Answer, Citation
  azure_clients/          # Azure SDK code: shared credential, OpenAI, AI Search, Blob (Entra ID auth)
  ingestion/              # pdf_loader, chunker, storage (local/Blob), processor (ingest_document)
  rag/                    # embeddings, vector_store, retriever, generator, pipeline
  api/                    # FastAPI app (main.py), routes, Services container
frontend/app.py           # Streamlit UI
scripts/                  # ingest.py, ask.py (CLI)
tests/                    # chunking, pipeline, AI Search, storage, API tests (all offline, with fakes)
data/raw, data/processed  # local PDFs and FAISS index (git-ignored)
```

## Cost notes

Phase 1 uses no cloud resources. From Phase 2 on, keep the corpus small (a handful of PDFs),
use Azure AI Search's free tier, set Container Apps `min replicas = 0`, and delete resource
groups you are not using. Azure OpenAI usage is billed against your credit, not a free quota.
