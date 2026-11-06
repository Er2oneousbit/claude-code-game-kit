# ---------------------------------------------------------------------------
# modules/linode/static/main.tf
# Purpose : A web build as a static site on Linode (Akamai) Object Storage: a private bucket whose objects anyone
#           can read, served over HTTPS at <bucket>.<region>.linodeobjects.com.
# Usage   : python tools/cloud/ship.py --target linode --kind static --site <web build> --plan
# Notes   : The root module sets obj_use_temp_keys, so no Object Storage keys are written anywhere. Linode's API has
#           no budget or billing-alert resource: set an alert in Cloud Manager by hand (ship.py says so). Validated
#           offline with OpenTofu; not applied to a real account yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    linode = { source = "linode/linode", version = "~> 4.0" }
    random = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

variable "name" { type = string }
variable "region" { type = string }
variable "site_dir" { type = string }

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

resource "linode_object_storage_bucket" "site" {
  label  = "${lower(var.name)}-site-${random_string.suffix.result}"
  region = var.region
  acl    = "private"
}

resource "linode_object_storage_object" "file" {
  for_each      = local.files
  bucket        = linode_object_storage_bucket.site.label
  region        = var.region
  key           = each.value
  source        = "${var.site_dir}/${each.value}"
  etag          = filemd5("${var.site_dir}/${each.value}")
  acl           = "public-read"
  content_type  = lookup(local.types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")
  force_destroy = true
}

output "url" {
  value = "https://${linode_object_storage_bucket.site.label}.${var.region}.linodeobjects.com/index.html"
}
