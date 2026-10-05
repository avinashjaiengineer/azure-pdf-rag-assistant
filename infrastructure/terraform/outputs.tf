output "ui_url" {
  value = "https://${azurerm_container_app.ui.ingress[0].fqdn}"
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "ci_client_id" {
  description = "Set as the AZURE_CLIENT_ID repository variable in GitHub."
  value       = azuread_application.ci.client_id
}

output "app_identity_client_id" {
  value = azurerm_user_assigned_identity.app.client_id
}

# Values for a local .env when running against these resources.
output "env" {
  value = {
    AZURE_OPENAI_ENDPOINT     = azurerm_cognitive_account.openai.endpoint
    AZURE_SEARCH_ENDPOINT     = "https://${azurerm_search_service.main.name}.search.windows.net"
    AZURE_STORAGE_ACCOUNT_URL = azurerm_storage_account.docs.primary_blob_endpoint
  }
}
