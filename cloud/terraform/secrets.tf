resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${local.name}/anthropic-api-key"
  description             = "Anthropic API key populated out-of-band after provisioning"
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret" "jwt_secret_key" {
  name                    = "${local.name}/jwt-secret-key"
  description             = "JWT signing key populated out-of-band after provisioning"
  recovery_window_in_days = 30
}

# Secret values are intentionally absent. Populate the two application secrets
# through an audited AWS CLI/console process after apply. RDS creates and rotates
# its own master credential because manage_master_user_password is enabled.

