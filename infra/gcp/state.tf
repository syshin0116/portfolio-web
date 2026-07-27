resource "google_storage_bucket" "terraform_state" {
  name     = "festive-ally-503605-v7-tfstate"
  project  = var.project_id
  location = var.region

  force_destroy               = false
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = 2592000
  }

  lifecycle {
    prevent_destroy = true
  }
}
