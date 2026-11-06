# ---------------------------------------------------------------------------
# modules/gcp/container/main.tf
# Purpose : One container image (a game server, a save-sync or leaderboard backend) on Cloud Run: HTTPS on its
#           run.app address, anyone may call it, at most one instance and none when idle, plus a budget alert on
#           the billing account, filtered to this project, that emails you.
# Usage   : python tools/cloud/ship.py --target gcp --kind container --image <image> --port <port> --plan
# Notes   : The image must be in a registry Cloud Run can pull (Artifact Registry, or a public one). Cloud Run is
#           request-driven: a server that holds long-lived connections needs a different product (verify for your
#           netcode). Validated offline with OpenTofu; not applied to a real project yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 8.0" }
  }
}

variable "name" { type = string }
variable "project" { type = string }
variable "location" { type = string }
variable "image" { type = string }
variable "port" { type = number }
variable "labels" { type = map(string) }
variable "billing_account" { type = string }
variable "budget_usd" { type = number }
variable "alert_email" { type = string }

resource "google_cloud_run_v2_service" "server" {
  name                = lower(var.name)
  project             = var.project
  location            = var.location
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # destroy must be able to remove it
  labels              = var.labels

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.image
      ports {
        container_port = var.port
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project
  location = var.location
  name     = google_cloud_run_v2_service.server.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_monitoring_notification_channel" "alert" {
  project      = var.project
  display_name = "${var.name} budget"
  type         = "email"
  labels       = { email_address = var.alert_email }
}

resource "google_billing_budget" "deploy" {
  billing_account = var.billing_account
  display_name    = "${var.name}-server-budget"

  budget_filter {
    projects = ["projects/${var.project}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.8
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.alert.id]
  }
}

output "url" {
  value = google_cloud_run_v2_service.server.uri
}
