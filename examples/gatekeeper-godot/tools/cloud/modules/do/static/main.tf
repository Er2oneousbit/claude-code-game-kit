# ---------------------------------------------------------------------------
# modules/do/static/main.tf
# Purpose : A web build as a static site on DigitalOcean: a private Spaces bucket whose files anyone can read,
#           behind the Spaces CDN, served over HTTPS at its cdn.digitaloceanspaces.com address.
# Usage   : python tools/cloud/ship.py --target do --kind static --site <web build> --plan
# Notes   : Spaces keys come from SPACES_ACCESS_KEY_ID / SPACES_SECRET_ACCESS_KEY in the environment (the provider's
#           own variables), never from a file. DigitalOcean's API has no budget resource: set a billing alert in the
#           control panel by hand (ship.py says so). Validated offline with OpenTofu; not applied yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    digitalocean = { source = "digitalocean/digitalocean", version = "~> 2.0" }
    random       = { source = "hashicorp/random", version = "~> 3.0" }
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

resource "digitalocean_spaces_bucket" "site" {
  name          = "${lower(var.name)}-site-${random_string.suffix.result}"
  region        = var.region
  acl           = "private"
  force_destroy = true # destroy removes the files too: nothing billable stays behind
}

resource "digitalocean_spaces_bucket_object" "file" {
  for_each     = local.files
  bucket       = digitalocean_spaces_bucket.site.name
  region       = var.region
  key          = each.value
  source       = "${var.site_dir}/${each.value}"
  etag         = filemd5("${var.site_dir}/${each.value}")
  acl          = "public-read"
  content_type = lookup(local.types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")
}

resource "digitalocean_cdn" "site" {
  origin = digitalocean_spaces_bucket.site.bucket_domain_name
}

output "url" {
  value = "https://${digitalocean_cdn.site.endpoint}/index.html"
}
