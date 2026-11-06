# ---------------------------------------------------------------------------
# modules/azure/container/main.tf
# Purpose : One container image (a game server, a save-sync or leaderboard backend) as an Azure Container App:
#           external HTTPS ingress only (no plain HTTP, no SSH), one small replica, its own resource group, plus a
#           monthly budget alert on that group.
# Usage   : python tools/cloud/ship.py --target azure --kind container --image <image> --port <port> --plan
# Notes   : No Log Analytics workspace (it bills by the gigabyte); add one when you need the logs. The image must be
#           public. Validated offline with OpenTofu; not applied to a real subscription yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.0" }
  }
}

variable "name" { type = string }
variable "location" { type = string }
variable "image" { type = string }
variable "port" { type = number }
variable "tags" { type = map(string) }
variable "budget_usd" { type = number }
variable "alert_email" { type = string }
variable "budget_start" {
  type        = string
  description = "First day of the current month, YYYY-MM-01T00:00:00Z (ship.py fills it in)"
}

resource "azurerm_resource_group" "server" {
  name     = "${var.name}-server-rg"
  location = var.location
  tags     = var.tags
}

resource "azurerm_container_app_environment" "server" {
  name                = "${var.name}-env"
  location            = var.location
  resource_group_name = azurerm_resource_group.server.name
  tags                = var.tags
}

resource "azurerm_container_app" "server" {
  name                         = substr(lower(var.name), 0, 32)
  container_app_environment_id = azurerm_container_app_environment.server.id
  resource_group_name          = azurerm_resource_group.server.name
  revision_mode                = "Single"
  tags                         = var.tags

  template {
    min_replicas = 0 # scales to zero when idle (verify the cold start suits your game)
    max_replicas = 1
    container {
      name   = "game"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  ingress {
    external_enabled           = true
    target_port                = var.port
    allow_insecure_connections = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_consumption_budget_resource_group" "deploy" {
  name              = "${var.name}-server-budget"
  resource_group_id = azurerm_resource_group.server.id
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
  value = "https://${azurerm_container_app.server.ingress[0].fqdn}"
}
