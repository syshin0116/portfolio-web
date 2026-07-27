terraform {
  backend "gcs" {
    bucket = "festive-ally-503605-v7-tfstate"
    prefix = "syshin0116.dev/gcp/foundation"
  }
}
