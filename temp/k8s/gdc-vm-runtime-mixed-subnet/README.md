# GDC VM Runtime Mixed Subnet Spike

This directory contains the live manifests used to answer a specific question:

- Can a VM Runtime VM and a normal Pod coexist on the same subnet in a Google Distributed Cloud cluster?

The manifests are split into two cases:

- `pod-network/`: supported baseline using the default GDC `pod-network`
- `shared-l2/`: custom shared-subnet experiment using the documented cross-node `vxlan0` fabric from the Compute Engine evaluation topology

These files are for spike validation only.

One environment-specific constraint matters for this eval cluster:

- the `local-shared` storage class still binds boot disks to node-affine local PVs on the sample cluster
- VM placement must follow the node selected by the imported boot disk
- if you want explicit same-node versus cross-node probes, choose those probe node selectors after the VM is running and you know its actual host node
