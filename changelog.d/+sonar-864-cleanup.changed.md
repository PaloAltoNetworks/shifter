**Internal code-quality cleanup of the GCP/GDC provisioner and portal notification
code.** Resolved the SonarCloud findings surfaced on the `dev` → `aws-dev`
promotion: replaced bare `Any` hints with specific types (kubernetes client
classes via `TYPE_CHECKING`, `botocore` `BaseClient`, Jinja `Template`, Django
user types), added missing docstrings, wrapped over-length lines, de-duplicated
string literals into constants, reduced over-parameterized helpers via small
frozen-dataclass parameter objects, and lowered the cognitive complexity of the
VPC-endpoint waiter. No runtime behavior change.
