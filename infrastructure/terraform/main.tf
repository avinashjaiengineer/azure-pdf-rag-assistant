locals {
  rg_name = "rg-pdf-rag-dev"
  tags = {
    project    = "azure-pdf-rag-assistant"
    managed_by = "terraform"
  }
}

resource "azurerm_resource_group" "main" {
  name     = local.rg_name
  location = var.location
  tags     = local.tags
}

# ---------------- Azure OpenAI (Phase 2) ----------------

resource "azurerm_cognitive_account" "openai" {
  name                  = "aoai-pdfrag-${var.suffix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = var.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "aoai-pdfrag-${var.suffix}"
  local_auth_enabled    = false # Entra ID only
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.chat_model.name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.chat_model.name
    version = var.chat_model.version
  }
  sku {
    name     = var.chat_model.sku
    capacity = var.chat_model.capacity
  }
}

resource "azurerm_cognitive_deployment" "embedding" {
  name                 = var.embedding_model.name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.embedding_model.name
    version = var.embedding_model.version
  }
  sku {
    name     = var.embedding_model.sku
    capacity = var.embedding_model.capacity
  }
}

# ---------------- Azure AI Search (Phase 3) ----------------

resource "azurerm_search_service" "main" {
  name                         = "srch-pdfrag-${var.suffix}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = var.search_location
  sku                          = "free"
  local_authentication_enabled = true # aadOrApiKey; the app itself only uses Entra ID
  authentication_failure_mode  = "http401WithBearerChallenge"
  semantic_search_sku          = "free" # free semantic ranker quota; unused for now
  tags                         = local.tags
}

# ---------------- Blob Storage (Phase 4) ----------------

resource "azurerm_storage_account" "docs" {
  name                            = "stpdfrag${var.suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = var.location
  account_kind                    = "StorageV2"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  access_tier                     = "Hot"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  tags                            = local.tags
}

resource "azurerm_storage_container" "documents" {
  name                  = "documents"
  storage_account_id    = azurerm_storage_account.docs.id
  container_access_type = "private"
}

# ---------------- Containers (Phase 6) ----------------

resource "azurerm_container_registry" "main" {
  name                = "acrpdfrag${var.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-pdfrag-${var.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "workspace-rgpdfragdevVI7N" # auto-named by `az containerapp env create`
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-pdfrag-${var.suffix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

locals {
  registry = azurerm_container_registry.main.login_server
  # A list (not a map) so order is stable: reordering env vars would roll a new revision.
  api_env = [
    { name = "AZURE_CLIENT_ID", value = azurerm_user_assigned_identity.app.client_id },
    { name = "LLM_PROVIDER", value = "azure" },
    { name = "EMBEDDING_PROVIDER", value = "azure" },
    { name = "VECTOR_STORE", value = "azure_search" },
    { name = "DOCUMENT_STORAGE", value = "blob" },
    { name = "AZURE_OPENAI_ENDPOINT", value = azurerm_cognitive_account.openai.endpoint },
    { name = "AZURE_SEARCH_ENDPOINT", value = "https://${azurerm_search_service.main.name}.search.windows.net" },
    { name = "AZURE_STORAGE_ACCOUNT_URL", value = azurerm_storage_account.docs.primary_blob_endpoint },
  ]
}

resource "azurerm_container_app" "api" {
  name                         = "ca-pdfrag-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  max_inactive_revisions       = 100
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = false # only reachable from inside the environment
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "ca-pdfrag-api"
      image  = "${local.registry}/pdf-rag-api:latest" # CI sets the real tag
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image] # owned by the CI deploy job
  }
}

resource "azurerm_container_app" "ui" {
  name                         = "ca-pdfrag-ui"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  max_inactive_revisions       = 100
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = local.registry
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8501
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }

    dynamic "ip_security_restriction" {
      for_each = { for i, cidr in var.ui_allowed_cidrs : "allow-${i}" => cidr }
      content {
        name             = ip_security_restriction.key
        ip_address_range = ip_security_restriction.value
        action           = "Allow"
      }
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "ca-pdfrag-ui"
      image  = "${local.registry}/pdf-rag-ui:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "API_URL"
        value = "http://${azurerm_container_app.api.name}"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
