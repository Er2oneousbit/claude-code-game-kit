# ---------------------------------------------------------------------------
# modules/aws/static/main.tf
# Purpose : A web build as a static site on AWS: a private S3 bucket behind CloudFront (HTTPS only, origin access
#           control, no public bucket), plus a monthly budget alert.
# Usage   : python tools/cloud/ship.py --target aws --kind static --site <web build> --plan   (writes the root module
#           that calls this one; never run tofu here by hand)
# Notes   : Tags come from the root module's provider default_tags (game-kit = <slug>). Validated offline with
#           OpenTofu; not applied to a real account yet (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" { type = string }
variable "site_dir" { type = string }
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

resource "aws_s3_bucket" "site" {
  bucket_prefix = "${var.name}-site-"
  force_destroy = true # destroy removes the files too: nothing billable stays behind
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_object" "file" {
  for_each     = local.files
  bucket       = aws_s3_bucket.site.id
  key          = each.value
  source       = "${var.site_dir}/${each.value}"
  etag         = filemd5("${var.site_dir}/${each.value}")
  content_type = lookup(local.types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  comment             = "${var.name} (game-kit)"

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS managed CachingOptimized (verify)
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "CloudFrontReadsTheSite"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_budgets_budget" "deploy" {
  name         = "${var.name}-site-budget"
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
  value = "https://${aws_cloudfront_distribution.site.domain_name}/"
}
