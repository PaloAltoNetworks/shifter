# KubeVirt + CDI Operators and Artifact Registry
#
# Cluster addons installed after GKE is running:
# - KubeVirt operator + CR (VM management on Kubernetes)
# - CDI operator + CR (VM disk image importing)
# - Artifact Registry repository for containerDisk images
#
# Uses the gavinbunney/kubectl provider to apply operator YAML manifests
# because the hashicorp/kubernetes provider requires CRDs to exist at
# plan time, which doesn't work for operator bootstrapping.

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.14.0"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
  }
}

# ------------------------------------------------------------------------------
# KubeVirt Operator
# Manages VirtualMachine CRDs, virt-controller, virt-handler DaemonSet, etc.
# ------------------------------------------------------------------------------

data "http" "kubevirt_operator" {
  url = "https://github.com/kubevirt/kubevirt/releases/download/${var.kubevirt_version}/kubevirt-operator.yaml"

  request_headers = {
    Accept = "application/yaml"
  }
}

data "kubectl_file_documents" "kubevirt_operator" {
  content = data.http.kubevirt_operator.response_body
}

resource "kubectl_manifest" "kubevirt_operator" {
  for_each  = data.kubectl_file_documents.kubevirt_operator.manifests
  yaml_body = each.value

  wait = true
}

# ------------------------------------------------------------------------------
# KubeVirt CR (triggers the operator to deploy virt components)
# ------------------------------------------------------------------------------

resource "kubectl_manifest" "kubevirt_cr" {
  yaml_body = <<-YAML
    apiVersion: kubevirt.io/v1
    kind: KubeVirt
    metadata:
      name: kubevirt
      namespace: kubevirt
    spec:
      configuration:
        developerConfiguration:
          useEmulation: false
        machineType: "q35"
  YAML

  wait            = true
  wait_for_rollout = false

  depends_on = [kubectl_manifest.kubevirt_operator]
}

# ------------------------------------------------------------------------------
# CDI (Containerized Data Importer) Operator
# Imports VM disk images from registries/URLs into PVs for KubeVirt.
# ------------------------------------------------------------------------------

data "http" "cdi_operator" {
  url = "https://github.com/kubevirt/containerized-data-importer/releases/download/${var.cdi_version}/cdi-operator.yaml"

  request_headers = {
    Accept = "application/yaml"
  }
}

data "kubectl_file_documents" "cdi_operator" {
  content = data.http.cdi_operator.response_body
}

resource "kubectl_manifest" "cdi_operator" {
  for_each  = data.kubectl_file_documents.cdi_operator.manifests
  yaml_body = each.value

  wait = true
}

# ------------------------------------------------------------------------------
# CDI CR (triggers the operator to deploy CDI components)
# ------------------------------------------------------------------------------

resource "kubectl_manifest" "cdi_cr" {
  yaml_body = <<-YAML
    apiVersion: cdi.kubevirt.io/v1beta1
    kind: CDI
    metadata:
      name: cdi
    spec:
      config:
        scratchSpaceStorageClass: ${var.storage_class}
  YAML

  wait            = true
  wait_for_rollout = false

  depends_on = [kubectl_manifest.cdi_operator]
}

# ------------------------------------------------------------------------------
# Artifact Registry (containerDisk images for KubeVirt VMs)
#
# KubeVirt VMs can boot from containerDisk volumes — OCI images that contain
# a VM disk (qcow2/raw) at /disk/. Stored here, pulled by nodes at VM start.
# This is the GCP equivalent of EC2 AMIs for range instances.
# ------------------------------------------------------------------------------

resource "google_artifact_registry_repository" "vm_images" {
  location      = var.region
  repository_id = "${var.name_prefix}-vm-images"
  description   = "ContainerDisk images for KubeVirt range VMs (Kali, Ubuntu, Windows, etc.)"
  format        = "DOCKER"
  project       = var.project_id

  labels = var.labels
}

# Allow GKE nodes to pull images from Artifact Registry
resource "google_artifact_registry_repository_iam_member" "gke_reader" {
  location   = google_artifact_registry_repository.vm_images.location
  repository = google_artifact_registry_repository.vm_images.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${var.gke_node_service_account_email}"
  project    = var.project_id
}

# Allow CI/CD service account to push images
resource "google_artifact_registry_repository_iam_member" "cicd_writer" {
  count = var.cicd_service_account_email != "" ? 1 : 0

  location   = google_artifact_registry_repository.vm_images.location
  repository = google_artifact_registry_repository.vm_images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.cicd_service_account_email}"
  project    = var.project_id
}
