#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <namespace> <probe-pod> [vm-name] [port]" >&2
  exit 2
fi

namespace="$1"
probe_pod="$2"
vm_name="${3:-podnet-vm}"
port="${4:-8080}"

export KUBECONFIG=/home/tfadmin/bmctl-workspace/cluster1/cluster1-kubeconfig

vm_ip_raw="$(kubectl get gvm "$vm_name" -n "$namespace" -o jsonpath='{.status.interfaces[0].ipAddresses[0]}')"
vm_ip="${vm_ip_raw%%/*}"
vm_node="$(kubectl get vmi "$vm_name" -n "$namespace" -o jsonpath='{.status.nodeName}')"
probe_node="$(kubectl get pod "$probe_pod" -n "$namespace" -o jsonpath='{.spec.nodeName}')"

echo "vm_name=$vm_name"
echo "vm_ip_raw=$vm_ip_raw"
echo "vm_ip=$vm_ip"
echo "vm_node=$vm_node"
echo "probe_pod=$probe_pod"
echo "probe_node=$probe_node"
echo
echo "== ping =="
kubectl exec -n "$namespace" "$probe_pod" -- ping -c 3 "$vm_ip"
echo
echo "== http =="
kubectl exec -n "$namespace" "$probe_pod" -- curl -fsS --max-time 10 "http://$vm_ip:$port/"
