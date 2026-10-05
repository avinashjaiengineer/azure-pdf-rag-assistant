variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
  default     = "89e6f120-704c-4720-a2ec-3711752c1a1c"
}

variable "suffix" {
  description = "Short unique suffix used in globally-unique resource names."
  type        = string
  default     = "487f"
}

variable "location" {
  description = "Primary region."
  type        = string
  default     = "eastus2"
}

variable "search_location" {
  description = "AI Search region (eastus2 had no free-tier capacity when this was created)."
  type        = string
  default     = "eastus"
}

variable "github_repository" {
  description = "owner/repo allowed to deploy via OIDC."
  type        = string
  default     = "avinashjaiengineer/azure-pdf-rag-assistant"
}

variable "github_oidc_subject" {
  description = "Exact OIDC subject GitHub presents for pushes to main (new repos use immutable owner/repo IDs)."
  type        = string
  default     = "repo:avinashjaiengineer@331991776/azure-pdf-rag-assistant@1405748607:ref:refs/heads/main"
}

variable "developer_object_ids" {
  description = "Entra object IDs of developers who run the app locally against Azure (az login)."
  type        = set(string)
  default     = ["549a007f-855d-44b0-b233-c3aceae6c171"]
}

variable "ui_allowed_cidrs" {
  description = "CIDRs allowed to reach the public UI."
  type        = list(string)
  default     = ["205.254.168.60/32"]
}

variable "chat_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "gpt-5-mini"
    version  = "2025-08-07"
    sku      = "GlobalStandard"
    capacity = 50 # thousand tokens per minute
  }
}

variable "embedding_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "text-embedding-3-small"
    version  = "1"
    sku      = "Standard"
    capacity = 120
  }
}
