# ---------------------------------------------------------------------------
# modules/aws/container/main.tf
# Purpose : One container image (a game server, a save-sync or leaderboard backend) on AWS Lightsail container
#           service: one small node, a public HTTPS endpoint, no SSH, plus a monthly budget alert.
# Usage   : python tools/cloud/ship.py --target aws --kind container --image <image> --port <port> --plan
# Notes   : Lightsail serves the endpoint over HTTPS on its own domain. The image must be public (or in a registry
#           Lightsail can pull). Validated offline with OpenTofu; not applied to a real account yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" { type = string }
variable "image" { type = string }
variable "port" { type = number }
variable "health_path" {
  type    = string
  default = "/"
}
variable "budget_usd" { type = number }
variable "alert_email" { type = string }

resource "aws_lightsail_container_service" "server" {
  name  = substr(var.name, 0, 63)
  power = "nano" # the smallest node (verify the price on the Lightsail pricing page)
  scale = 1
}

resource "aws_lightsail_container_service_deployment_version" "server" {
  service_name = aws_lightsail_container_service.server.name

  container {
    container_name = "game"
    image          = var.image
    ports          = { tostring(var.port) = "HTTP" }
  }

  public_endpoint {
    container_name = "game"
    container_port = var.port
    health_check {
      path = var.health_path
    }
  }
}

resource "aws_budgets_budget" "deploy" {
  name         = "${var.name}-server-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

output "url" {
  value = aws_lightsail_container_service.server.url
}
