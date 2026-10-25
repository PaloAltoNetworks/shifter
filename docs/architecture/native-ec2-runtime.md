# Native EC2 range runtime

The AWS RAES runtime realizes the same immutable plan and isolated adapter
protocol used by GCE. Tenant organization administrators select installed
adapters; core supplies provider observations and the guest management channel.
The adapter receives `provider=aws` and cannot import core application code or
obtain a cloud identity through the guest.

## Ownership and admission

Normal AWS launches persist `range_backend=ec2` and `live_fire` admission.
The Engine creates a separate, write-once `resource_generation` UUID when it
creates the range. Every provision and destroy input retains that UUID. Cloud
resources carry it alongside environment, request, range, and opaque subject
tags; operation IDs continue to fence allocation, dispatch, and result delivery.
A cleanup operation must not use its own operation ID as the resource owner.
Existing GCE inputs remain compatible without this optional wire field. EC2
requires it. Legacy unbound rows are not inferred to be native EC2 resources.

The initial EC2 runtime supports cold VM creation. Warm activation remains
unsupported and uses the capability registry's cold fallback. Image preflight
checks the exact AMI, root snapshot, platform, architecture, CPU and memory,
then preserves the selected management username and port. Image mappings and
artifact bindings are captured at launch, rather than reread during execution.

## Networking and identities

The EKS platform owns its peering to the range VPC independently of the optional
model broker. Terraform move declarations preserve peering and route ownership
when upgrading earlier broker deployments. The applied EKS subnet CIDRs supply
`PORTAL_NETWORK_CIDRS` and `ACCESS_NETWORK_CIDRS` to provisioner Jobs.

Each range owns private subnets, security groups, and a route table. The current
tenant allocator supplies open `/28` network intent. Authored CIDRs, multiple
NICs per guest, and ordered ACLs are rejected when the backend cannot preserve
them; it never silently rewrites those semantics. Range-local traffic, declared
service and participant ports, management SSH, and an optional exact broker TLS
destination are the permitted lanes. No default internet route is copied into
the range table. Actual routes and associations must match before guest creation.
The current EC2 backend does not realize `allowlist` egress. CMS and Engine
reject that workspace policy before launch dispatch; the provisioner repeats the
check before allocation. Other providers retain their existing capabilities.

The broker publishes its actual private NLB listener addresses as
`MODEL_BROKER_GUEST_CIDRS`. These are distinct from STS and model-provider endpoint
addresses. Only the broker TLS listener is admitted as guest model egress.
Disabling model access does not remove the platform's range-management peering.

Native guests have an encrypted, disposable root disk, one private IPv4 NIC,
IMDSv2 with hop limit one, and no instance profile. The provisioner issues and
pins SSH host keys and keeps management private keys in deployment-encrypted
Secrets Manager entries. Existing guests cannot regenerate missing management
identities. Authored local accounts cannot overwrite a custom image management
login. When participant SSH uses a different server, core reads its host key
through the pinned management connection instead of reusing the management
server key. Such images must supply `ssh-keyscan` on the management host.

Windows bootstrap admits only the configured management SSH port through the
guest firewall. It preserves firewall profiles and unrelated rules; any other
guest firewall changes belong to the image or explicitly bound adapter.

Native resources use `ManagedBy=shifter`; their IAM grants require
that manager, system, and environment ownership instead of claiming Terraform
management. Observations reject extra NICs, secondary or IPv6 addresses, public
associations, and retained attachments.

## Completion and cleanup

Inline composition is delivered over the pinned management channel. Account,
directory, content, enrollment, and isolated adapter stages precede independent
composition, OS, and substrate readback. A failed stage enters owned cleanup and
cannot produce a ready result.

Teardown does not load the current adapter, image registry, or broker settings.
It first inventories every resource within the retained ownership scope, refuses
foreign generations and attachments, terminates guests, waits for termination,
and removes remaining owned dependencies. Provider errors, pagination beyond
the bound, or residual resources cannot establish absence. Credentials and
subnet reservations are retired only after resource absence is established.
Failed provisioning follows the same independent absence requirement before
retiring credentials and releasing its operation-fenced reservation. An incomplete
observation or failed credential cleanup retains capacity for safe recovery.
Client initialization precedes allocation, so a client failure cannot reserve capacity.

Local contract, provider-mock, transport, and Terraform tests are development
evidence. AWS and GCP live qualification, including tenant installation and a
real range lifecycle, remain separate acceptance steps.
