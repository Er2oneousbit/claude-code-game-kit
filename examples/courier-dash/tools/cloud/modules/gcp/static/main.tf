# ---------------------------------------------------------------------------
# modules/gcp/static/main.tf
# Purpose : A web build as a static site on Google Cloud: a Cloud Storage bucket whose objects anyone can read,
#           served over HTTPS at storage.googleapis.com/<bucket>/, plus a budget alert on the billing account,
#           filtered to this project, that emails you.
# Usage   : python tools/cloud/ship.py --target gcp --kind static --site <web build> --plan
# Notes   : Uniform bucket-level access (no per-object ACLs); the bucket and the alert channel carry the game-kit
#           label. A custom domain needs a load balancer or Firebase Hosting (not made here). Validated offline with
#           OpenTofu; not applied to a real project yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 8.0" }
    random = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

variable "name" { type = string }
variable "project" { type = string }
variable "location" { type = string }
variable "site_dir" { type = string }
variable "labels" { type = map(string) }
variable "billing_account" { type = string }
variable "budget_usd" { type = number }
variable "alert_email" { type = string }

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

resource "google_storage_bucket" "site" {
  depends_on                  = [google_project_service.api]
  name                        = "${lower(var.name)}-site-${random_string.suffix.result}"
  project                     = var.project
  location                    = var.location
  uniform_bucket_level_access = true
  force_destroy               = true # destroy removes the files too: nothing billable stays behind
  labels                      = var.labels

  website {
    main_page_suffix = "index.html"
  }
}

resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.site.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_storage_bucket_object" "file" {
  for_each     = local.files
  bucket       = google_storage_bucket.site.name
  name         = each.value
  source       = "${var.site_dir}/${each.value}"
  content_type = lookup(local.types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")
}

# The APIs these resources need, switched on (a new project has them off). Left on at destroy: other things in the
# project may use them.
resource "google_project_service" "api" {
  for_each           = toset(["storage.googleapis.com", "monitoring.googleapis.com", "billingbudgets.googleapis.com"])
  project            = var.project
  service            = each.value
  disable_on_destroy = false
}

# Budget filters name the project by its number, not its ID
data "google_project" "current" {
  project_id = var.project
}

resource "google_monitoring_notification_channel" "alert" {
  project      = var.project
  display_name = "${var.name} budget"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.api]
}

resource "google_billing_budget" "deploy" {
  billing_account = var.billing_account
  depends_on      = [google_project_service.api]
  display_name    = "${var.name}-site-budget"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
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
  value = "https://storage.googleapis.com/${google_storage_bucket.site.name}/index.html"
}
