variable "location" {
  description = "Azure region for the CCCP hub."
  type        = string
  default     = "centralus"
}

variable "resource_group_name" {
  description = "Resource group name for the CCCP hub."
  type        = string
  default     = "cccp-hub"
}

variable "storage_account_name" {
  description = "Storage account name (3-24 chars, lowercase alphanumeric, globally unique). Leave null to auto-generate cccp<random>."
  type        = string
  default     = null
}

variable "container_name" {
  description = "Blob container that holds all cells (as prefixes)."
  type        = string
  default     = "cccp"
}

variable "subscription_id" {
  description = "Azure subscription ID for the CCCP hub. Leave null to use the az CLI's currently selected subscription."
  type        = string
  default     = null
}
