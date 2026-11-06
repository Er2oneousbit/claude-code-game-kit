# ---------------------------------------------------------------------------
# modules/do/container/main.tf
# Purpose : One container image (a game server, a save-sync or leaderboard backend) on DigitalOcean App Platform:
#           one small instance, HTTPS on its ondigitalocean.app address, no SSH.
# Usage   : python tools/cloud/ship.py --target do --kind container --image <image> --port <port> --plan
# Notes   : ship.py splits the image reference into App Platform's registry fields (Docker Hub or GHCR). DigitalOcean's
#           API has no budget resource: set a billing alert in the control panel by hand (ship.py says so). Validated
#           offline with OpenTofu; not applied yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    digitalocean = { source = "digitalocean/digitalocean", version = "~> 2.0" }
  }
}

variable "name" { type = string }
variable "region" { type = string }
variable "registry_type" { type = string } # DOCKER_HUB or GHCR
variable "registry" { type = string }      # the Docker Hub namespace or the GHCR owner
variable "repository" { type = string }
variable "tag" { type = string }
variable "port" { type = number }

resource "digitalocean_app" "server" {
  spec {
    name   = substr(lower(var.name), 0, 32)
    region = var.region

    service {
      name               = "game"
      instance_count     = 1
      instance_size_slug = "apps-s-1vcpu-0.5gb" # the smallest size (verify the slug and price on the pricing page)
      http_port          = var.port

      image {
        registry_type = var.registry_type
        registry      = var.registry
        repository    = var.repository
        tag           = var.tag
      }
    }
  }
}

output "url" {
  value = digitalocean_app.server.live_url
}
