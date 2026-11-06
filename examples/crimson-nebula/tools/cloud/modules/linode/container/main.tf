# ---------------------------------------------------------------------------
# modules/linode/container/main.tf
# Purpose : One container image (a game server, a save-sync or leaderboard backend) on the smallest Linode VM:
#           cloud-init installs Docker and runs the image behind Caddy, which serves it over HTTPS on your domain
#           (a Let's Encrypt certificate); a firewall drops everything inbound but 80 and 443, so no SSH.
# Usage   : python tools/cloud/ship.py --target linode --kind container --image <image> --port <port>
#           --domain game.example.com --plan     then point the domain's A record at the address it prints
# Notes   : A bare IP address cannot get a public certificate, hence the domain. The root password is random and
#           never used (no SSH); it sits only in the local state, which ship.py keeps out of git. Linode's API has no
#           budget or billing-alert resource: set one in Cloud Manager by hand (ship.py says so). Validated offline
#           with OpenTofu; not applied to a real account yet (verify).
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
variable "image" { type = string }
variable "port" { type = number }
variable "domain" { type = string }
variable "tags" { type = list(string) }

resource "random_password" "root" {
  length  = 32
  special = true
}

locals {
  # cloud-init: Docker from Debian's packages, the game and Caddy on one network (verify on a real VM)
  user_data = <<-EOT
    #cloud-config
    package_update: true
    packages: [docker.io]
    write_files:
      - path: /etc/caddy/Caddyfile
        content: |
          ${var.domain} {
            reverse_proxy game:${var.port}
          }
    runcmd:
      - systemctl enable --now docker
      - docker network create kit
      - docker run -d --restart unless-stopped --name game --network kit ${var.image}
      - docker run -d --restart unless-stopped --name caddy --network kit -p 80:80 -p 443:443 -v /etc/caddy/Caddyfile:/etc/caddy/Caddyfile -v caddy_data:/data caddy:2
  EOT
}

resource "linode_instance" "server" {
  label     = substr(lower(var.name), 0, 64)
  region    = var.region
  type      = "g6-nanode-1" # the smallest plan (verify the price on Linode's pricing page)
  image     = "linode/debian12"
  root_pass = random_password.root.result
  tags      = var.tags

  metadata {
    user_data = base64encode(local.user_data)
  }
}

resource "linode_firewall" "server" {
  label           = substr("${lower(var.name)}-fw", 0, 32)
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  linodes         = [linode_instance.server.id]
  tags            = var.tags

  inbound {
    label    = "https"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "443"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }

  inbound {
    label    = "http-for-certificates"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "80"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }
}

output "url" {
  value = "https://${var.domain}/"
}

output "address" {
  value = tolist(linode_instance.server.ipv4)[0]
}
