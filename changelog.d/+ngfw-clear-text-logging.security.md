**Stopped the NGFW provisioner from dumping full Terraform output dicts to the
logs.** `ngfw_terraform.py` logged `json.dumps(output_data)` after both the AWS
and GDC VM-Series applies; those output dicts carry a Secret Manager /
Secrets Manager reference (`ssh_key_secret_id` / `ssh_key_secret_arn`), so the
dump wrote the reference in clear text (CodeQL `py/clear-text-logging-sensitive-data`)
and would have leaked any future sensitive output field. Both sites now log
only the non-sensitive correlation IDs (`request_id`, `instance_id`) and an
output-field count, via `log_redact.safe_log_value`.
