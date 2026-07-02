# CCCP v2 — Azure Blob Storage infrastructure (the "general" / default hub).
#
# Provisions durable infra only: a resource group, a storage account with
# hierarchical namespace enabled (for clean prefix-scoped SAS), and the `cccp`
# container that holds every cell as a prefix.
#
# The SAS credential is deliberately NOT managed here — apply.sh mints it at
# apply time so the credential's lifecycle stays out of Terraform state.
#
# Rarely run, and only via apply.sh.

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  # Which subscription to deploy into. Leave var.subscription_id null to use
  # whatever the az CLI has selected (see: az account show).
  subscription_id = var.subscription_id
  features {}
}

# Storage account names are globally unique, 3-24 chars, lowercase alphanumeric.
# A random suffix keeps `terraform apply` zero-friction; override via tfvars if
# a memorable name is wanted.
resource "random_string" "suffix" {
  length  = 10
  special = false
  upper   = false
}

resource "azurerm_resource_group" "cccp" {
  name     = var.resource_group_name
  location = var.location
}

resource "azurerm_storage_account" "cccp" {
  name                = coalesce(var.storage_account_name, "cccp${random_string.suffix.result}")
  resource_group_name = azurerm_resource_group.cccp.name
  location            = azurerm_resource_group.cccp.location

  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  # Flat namespace (HNS off — the default). With HNS, blob "directories" become
  # real objects that persist and need depth-first deletion: needless friction
  # for CCCP's tiny chat-sized data. HNS's one upside — per-cell SAS scoping — is
  # handled instead by per-project containers via the .env credential model.
  # We enabled HNS initially and turned it back off; do not re-enable without
  # re-litigating the deletion-friction tradeoff.

  # CCCP only ever talks HTTPS.
  https_traffic_only_enabled = true
  min_tls_version            = "TLS1_2"
}

resource "azurerm_storage_container" "cccp" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.cccp.id
  container_access_type = "private"
}
