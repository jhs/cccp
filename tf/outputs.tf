output "resource_group_name" {
  value = azurerm_resource_group.cccp.name
}

output "storage_account_name" {
  value = azurerm_storage_account.cccp.name
}

output "container_name" {
  value = azurerm_storage_container.cccp.name
}

output "blob_endpoint" {
  value = azurerm_storage_account.cccp.primary_blob_endpoint
}
