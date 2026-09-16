{{- define "shifter.labels" -}}
app.kubernetes.io/name: shifter
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "shifter.partOfLabels" -}}
{{ include "shifter.labels" . }}
app.kubernetes.io/part-of: shifter
{{- end }}

{{- define "shifter.podSecurityContext" -}}
securityContext:
  seccompProfile:
    type: {{ .Values.security.pod.seccompProfile }}
{{- end }}

{{- define "shifter.accessNodePlacement" -}}
{{- if .Values.capabilities.gcpAccessNodePool }}
nodeSelector:
  node-restriction.kubernetes.io/shifter-pool: access
tolerations:
  - key: dedicated
    operator: Equal
    value: access
    effect: NoSchedule
{{- end }}
{{- end }}

{{- define "shifter.podAntiAffinity" -}}
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app.kubernetes.io/part-of: shifter
              app.kubernetes.io/component: {{ .component }}
          topologyKey: kubernetes.io/hostname
{{- end }}

{{- define "shifter.containerSecurityContextApp" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: {{ .Values.security.app.runAsUser }}
  runAsGroup: {{ .Values.security.app.runAsGroup }}
{{- end }}

{{- define "shifter.containerSecurityContextGuacd" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: {{ .Values.security.guacd.runAsUser }}
  runAsGroup: {{ .Values.security.guacd.runAsGroup }}
{{- end }}

{{- define "shifter.containerSecurityContextGuacamole" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: {{ .Values.security.guacamole.runAsUser }}
  runAsGroup: {{ .Values.security.guacamole.runAsGroup }}
{{- end }}

{{- define "shifter.tmpVolumeMount" -}}
volumeMounts:
  - name: tmp
    mountPath: /tmp
{{- end }}

{{- define "shifter.tmpVolume" -}}
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: {{ .Values.tmpVolume.sizeLimit | quote }}
{{- end }}

{{- define "shifter.runtimeConfigChecksum" -}}
{{ toJson (dict "runtimeEnv" .Values.runtimeEnv "jobsNamespace" .Values.namespaces.jobs "provisionerServiceAccount" .Values.serviceAccounts.provisioner.name) | sha256sum }}
{{- end }}

{{- define "shifter.portalImage" -}}
{{ .Values.images.platform }}
{{- end }}

{{- define "shifter.guacdImage" -}}
{{ .Values.images.guacd }}
{{- end }}

{{- define "shifter.guacamoleClientImage" -}}
{{ .Values.images.guacamoleClient }}
{{- end }}
