# ---------------------------------------------------------------------------
# modules/azure/static/main.tf
# Purpose : A web build as a static site on Azure: a storage account's static website (HTTPS, TLS 1.2 minimum, no
#           public containers), in its own resource group, plus a monthly budget alert on that group.
# Usage   : python tools/cloud/ship.py --target azure --kind static --site <web build> --plan
# Notes   : The static website endpoint serves the $web container's files to anyone; nothing else in the account is
#           public. Validated offline with OpenTofu; not applied to a real subscription yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.0" }
    random  = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

variable "name" { type = string }
variable "location" { type = string }
variable "site_dir" { type = string }
variable "tags" { type = map(string) }
variable "budget_usd" { type = number }
variable "alert_email" { type = string }
variable "budget_start" {
  type        = string
  description = "First day of the current month, YYYY-MM-01T00:00:00Z (ship.py fills it in)"
}

locals {
  files = fileset(var.site_dir, "**")
  types = {
    html = "text/html", htm = "text/html", js = "text/javascript", mjs = "text/javascript", css = "text/css",
    json = "application/json", wasm = "application/wasm", png = "image/png", jpg = "image/jpeg", jpeg = "image/jpeg",
    gif  = "image/gif", webp = "image/webp", svg = "image/svg+xml", ico = "image/x-icon", ogg = "audio/ogg",
    mp3  = "audio/mpeg", wav = "audio/wav", woff = "font/woff", woff2 = "font/woff2", ttf = "font/ttf",
    txt  = "text/plain", xml = "application/xml"
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "site" {
  name     = "${var.name}-site-rg"
  location = var.location
  tags     = var.tags
}

resource "azurerm_storage_account" "site" {
  # 3-24 lowercase letters and digits, unique across Azure
  name                            = substr("${replace(lower(var.name), "/[^a-z0-9]/", "")}${random_string.suffix.result}", 0, 24)
  resource_group_name             = azurerm_resource_group.site.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = var.tags
}

resource "azurerm_storage_account_static_website" "site" {
  storage_account_id = azurerm_storage_account.site.id
  index_document     = "index.html"
}

resource "azurerm_storage_blob" "file" {
  for_each = local.files
  name     = each.value
  # The $web container the static website made (verify the ID form against a real account)
  storage_container_id = "${azurerm_storage_account.site.id}/blobServices/default/containers/$web"
  type                 = "Block"
  source               = "${var.site_dir}/${each.value}"
  content_md5          = filemd5("${var.site_dir}/${each.value}")
  content_type         = lookup(local.types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")
  depends_on           = [azurerm_storage_account_static_website.site]
}

resource "azurerm_consumption_budget_resource_group" "deploy" {
  name              = "${var.name}-site-budget"
  resource_group_id = azurerm_resource_group.site.id
  amount            = var.budget_usd
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start
  }

  notification {
    operator       = "GreaterThan"
    threshold      = 80
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }
}

output "url" {
  value = azurerm_storage_account.site.primary_web_endpoint
}
