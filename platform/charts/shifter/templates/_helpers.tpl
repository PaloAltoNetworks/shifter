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
    emptyDir: {}
{{- end }}

{{- define "shifter.runtimeConfigChecksum" -}}
{{ toJson .Values.runtimeEnv | sha256sum }}
{{- end }}

{{- define "shifter.guacamoleSecretChecksum" -}}
{{ toJson .Values.guacamoleRuntimeSecret.stringData | sha256sum }}
{{- end }}

{{- define "shifter.portalImage" -}}
{{ printf "%s:%s" .Values.images.portal.repository .Values.images.portal.tag }}
{{- end }}

{{- define "shifter.guacdImage" -}}
{{ printf "%s:%s" .Values.images.guacd.repository .Values.images.guacd.tag }}
{{- end }}

{{- define "shifter.guacamoleClientImage" -}}
{{ printf "%s:%s" .Values.images.guacamoleClient.repository .Values.images.guacamoleClient.tag }}
{{- end }}
