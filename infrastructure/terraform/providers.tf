terraform {
  required_version = ">= 1.7" # for_each in import blocks

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }

  # State lives in a separate resource group (bootstrapped once with az CLI, see README),
  # so destroying the app resource group can never destroy the state. Entra ID auth only.
  backend "azurerm" {
    resource_group_name  = "rg-pdf-rag-tfstate"
    storage_account_name = "sttfstate487f"
    container_name       = "tfstate"
    key                  = "pdf-rag-dev.tfstate"
    use_azuread_auth     = true
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  storage_use_azuread             = true   # shared-key access is disabled on the storage account
  resource_provider_registrations = "none" # providers were registered explicitly
}

provider "azuread" {}
