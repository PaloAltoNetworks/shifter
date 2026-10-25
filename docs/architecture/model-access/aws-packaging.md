# AWS model broker deployment

The EKS installer accepts closed `settings.model_broker` intent and a separate
`settings.model_broker_runtime` provider/accounting binding. Transport and IAM
metadata enter Terraform; public CA trust and versioned Kubernetes Secret
references enter the chart. Provider keys, signing-key bytes and private TLS keys
never enter either configuration projection. Tenant adapters select approved
logical model aliases through admitted grants; they cannot change this deployment
policy or gain provider IAM permissions.

The broker has its own exact-subject IRSA role, which can assume only the generated
invocation roles. Each invocation role permits count/invoke/stream operations on
one explicit regional foundation model. There are no broker database, platform
secret, object-store, IAM-management or guest credentials. The provisioner has a
distinct identity used only for the enrollment control operation. The old shared
range-instance Bedrock grant is removed when the range stack is applied.

This implementation accepts regional Anthropic foundation-model IDs with native
Bedrock Runtime token counting. Cross-region inference profiles and the Mantle
transport are not yet supported. A model/version must be independently qualified
for count and inference in the configured region before activation. The installer
requires an enabled v3 accounting catalog, exact shard/provider bindings, approved
pricing and versioned fingerprint-key Secret references for active replicas.

Terraform owns a private IPv4 NLB, a TCP 443 listener, and an IP target group on
8443 with client IP preservation. TLS terminates in the broker pod. The chart
registers only the broker Service endpoints through `TargetGroupBinding`; it does
not create another load balancer. Readiness probes use HTTPS `/health/ready`.
The NLB security group admits only configured range subnets. Broker NetworkPolicy
also allows the EKS private subnet health-check sources, but guest authorization
still requires the actual socket peer to belong to the grant's reserved subnet.
Forwarded headers and PROXY protocol are never authorization inputs.

The installer reads the existing range VPC and route table from the published
`/shifter/<environment>/range/` contract. It creates a direct EKS/range peering,
range routes to the private broker subnets and EKS return routes to admitted
guest subnets. A private DNS zone for the exact broker hostname is associated
with both VPCs. Networks must be disjoint and every admitted subnet must belong
to the range VPC. There is no public DNS/listener or Transit Gateway dependency.
Per-range subnet route tables must retain this private route during realization.

STS and Bedrock Runtime use dedicated interface endpoints with private DNS.
The rendered broker policy permits only their observed ENI `/32` addresses on
443, cluster DNS and the authenticated Engine control listener. General
application egress policies explicitly exclude the broker, including after
broker disablement while old pods drain. The broker disables EC2 metadata
credential discovery. IRSA projects its workload token; it does not grant the
broker Kubernetes API access.

Deployment requires applying the updated range stack to revoke the legacy guest
grant, then the EKS stack and chart through the normal installer. Supply distinct
broker/control TLS Secrets, a trust ConfigMap and versioned HMAC Secrets through
the deployment secret mechanism. The public guest CA bundle must validate both
broker and control certificates; it must contain certificates only. The protected
Terraform input must match the root broker intent, and applied Terraform readback
must match the root intent, region, account, inventory and provisioner identity
before Helm can mutate the release.

Offline tests exercise Terraform resources and rejection conditions, installation
binding and the chart's combined network policies. They are not live qualification.
AWS acceptance still requires range realization/enrollment, actual source-peer
readback, effective IAM and endpoint-denial tests, approved-client inference,
budget/revocation/refresh and cleanup evidence. SDK or adapter compatibility alone
does not establish those properties.

References: [NLB target attributes](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/edit-target-group-attributes.html),
[TargetGroupBinding](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/targetgroupbinding/targetgroupbinding/),
[Bedrock token counting](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html).

Credential transport uses a bounded regional SDK session before resolving the
workload identity. The same two-second connection/read timeouts and single attempt
apply to implicit web-identity refresh and explicit role assumption; configuring
only the final service client would leave the refresh on SDK defaults. Proxy
environment variables are not used by these STS clients.

The private broker NLB has deletion protection enabled. Deployment teardown must
explicitly disable that protection before destroying the load balancer. It uses
TCP passthrough for guest TLS, so AWS NLB access logging is unavailable (AWS only
logs TLS listeners); broker request metadata and VPC flow logs remain the audit
surfaces. See the narrowly scoped ADR-004-R11 scanner exception.
