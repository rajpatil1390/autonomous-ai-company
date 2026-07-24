terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80, < 7.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0, < 5.0"
    }
  }

  # Supply bucket, key, region, encryption, and locking configuration at init.
  # Backend credentials must come from the AWS credential chain, never this file.
  backend "s3" {}
}

