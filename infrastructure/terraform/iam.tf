# Least-privilege access. Three kinds of principal:
#   app        - the Container Apps' managed identity (runtime)
#   developers - humans running the app locally with `az login`
#   ci         - GitHub Actions via OIDC: push images, roll the two container apps

locals {
  # What the running app (and a developer running it locally) needs.
  runtime_roles = {
    openai_user    = { role = "Cognitive Services OpenAI User", scope = azurerm_cognitive_account.openai.id }
    search_data    = { role = "Search Index Data Contributor", scope = azurerm_search_service.main.id }
    search_service = { role = "Search Service Contributor", scope = azurerm_search_service.main.id } # creates the index
    blob_data      = { role = "Storage Blob Data Contributor", scope = azurerm_storage_account.docs.id }
  }

  developer_roles = {
    for pair in setproduct(var.developer_object_ids, keys(local.runtime_roles)) :
    "${pair[0]}/${pair[1]}" => merge(local.runtime_roles[pair[1]], { principal = pair[0] })
  }

  ci_roles = {
    acr_push   = { role = "AcrPush", scope = azurerm_container_registry.main.id }
    deploy_api = { role = "Container Apps Contributor", scope = azurerm_container_app.api.id }
    deploy_ui  = { role = "Container Apps Contributor", scope = azurerm_container_app.ui.id }
  }
}

# ---------------- App managed identity ----------------

resource "azurerm_role_assignment" "app" {
  for_each             = merge(local.runtime_roles, { acr_pull = { role = "AcrPull", scope = azurerm_container_registry.main.id } })
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------- Developers ----------------

resource "azurerm_role_assignment" "developer" {
  for_each             = local.developer_roles
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = each.value.principal
  principal_type       = "User"
}

# ---------------- GitHub Actions (OIDC) ----------------

resource "azuread_application" "ci" {
  display_name = "gh-pdfrag-ci"
}

resource "azuread_service_principal" "ci" {
  client_id = azuread_application.ci.client_id
}

resource "azuread_application_federated_identity_credential" "ci_main" {
  application_id = azuread_application.ci.id
  display_name   = "main-branch"
  description    = "GitHub Actions on ${var.github_repository} main branch"
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = var.github_oidc_subject
  audiences      = ["api://AzureADTokenExchange"]
}

resource "azurerm_role_assignment" "ci" {
  for_each             = local.ci_roles
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azuread_service_principal.ci.object_id
  principal_type       = "ServicePrincipal"
}
