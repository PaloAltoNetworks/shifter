Moved GCP dev VM guest password environment values out of the generated
`platform-runtime` ConfigMap into a generated Kubernetes Secret and wired
runtime Deployments to load those values via `secretRef`.
