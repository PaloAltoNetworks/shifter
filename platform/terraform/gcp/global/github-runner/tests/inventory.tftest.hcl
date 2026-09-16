mock_provider "google" {}

variables {
  project_id  = "example-runner"
  environment = "unseen-customer"
  name_prefix = "cust-unseen"
  region      = "us-central1"
  zone        = "us-central1-a"
}

run "unseen_inventory_runner" {
  command = plan
  assert {
    condition     = output.runner_names == ["cust-unseen-runner-1"]
    error_message = "Inventory owns stable runner names independently of the profile or purpose."
  }
  assert {
    condition     = length(google_compute_instance.runner[0].network_interface[0].access_config) == 0
    error_message = "An unseen deployment must retain private-only runners."
  }
}

run "legacy_names_preserved" {
  command = plan
  variables {
    name_prefix = null
  }
  assert {
    condition     = output.runner_names == ["shifter-unseen-customer-runner-1"]
    error_message = "Legacy callers must preserve existing resource names until cutover."
  }
}
