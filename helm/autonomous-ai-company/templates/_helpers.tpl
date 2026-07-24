{{/* Stable names preserve the existing Kubernetes resource contract. */}}
{{- define "autonomous-ai-company.name" -}}
autonomous-ai-company
{{- end }}

{{- define "autonomous-ai-company.fullname" -}}
autonomous-ai-company-api
{{- end }}

{{- define "autonomous-ai-company.configMapName" -}}
autonomous-ai-company-config
{{- end }}

{{- define "autonomous-ai-company.selectorLabels" -}}
app.kubernetes.io/name: {{ include "autonomous-ai-company.name" . }}
app.kubernetes.io/component: api
{{- end }}

{{- define "autonomous-ai-company.labels" -}}
{{ include "autonomous-ai-company.selectorLabels" . }}
app.kubernetes.io/part-of: {{ include "autonomous-ai-company.name" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
