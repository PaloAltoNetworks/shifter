Force the regional STS endpoint for the POLARIS a14-kali agent container. The
bootstrap verify runs `aws sts get-caller-identity` inside a14-kali, but the
container's aws-config set only `region`, so the CLI used the global
`sts.amazonaws.com` endpoint, which a14-kali cannot resolve (only the regional
`sts.<region>` endpoint is pinned in the container's extra_hosts). Add
`sts_regional_endpoints = regional` to the container aws-config so STS calls use
the pinned regional endpoint, and surface the get-caller-identity error in the
verify output instead of discarding it with `2>/dev/null`.
