{{/*
─────────────────────────────────────────────────────────────────────────────
AetherOS Helm Chart — Helper Templates
─────────────────────────────────────────────────────────────────────────────
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "aetheros.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
We truncate at 63 chars because some Kubernetes name fields have that limit.
If .Values.fullnameOverride is set it takes priority; otherwise we compose
<release>-<chart> (or just <release> if the release name already contains
the chart name).
*/}}
{{- define "aetheros.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label value: <name>-<version>.
*/}}
{{- define "aetheros.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "aetheros.labels" -}}
helm.sh/chart: {{ include "aetheros.chart" . }}
{{ include "aetheros.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: aetheros
{{- end }}

{{/*
Selector labels — used in matchLabels and Service selectors.
*/}}
{{- define "aetheros.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aetheros.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "aetheros.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "aetheros.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
ConfigMap name.
*/}}
{{- define "aetheros.configMapName" -}}
{{- printf "%s-config" (include "aetheros.fullname" .) }}
{{- end }}

{{/*
Secret name.
*/}}
{{- define "aetheros.secretName" -}}
{{- printf "%s-secret" (include "aetheros.fullname" .) }}
{{- end }}

{{/*
PVC name.
*/}}
{{- define "aetheros.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-artifacts" (include "aetheros.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Construct DATABASE_URL from sub-chart values when postgresql.enabled=true
and the user has not set secrets.DATABASE_URL explicitly.
Returns the full asyncpg connection string.
*/}}
{{- define "aetheros.databaseURL" -}}
{{- if .Values.secrets.DATABASE_URL }}
{{- .Values.secrets.DATABASE_URL }}
{{- else if .Values.postgresql.enabled }}
{{- $host := printf "%s-postgresql" .Release.Name }}
{{- $user := .Values.postgresql.auth.username }}
{{- $pass := .Values.postgresql.auth.password }}
{{- $db   := .Values.postgresql.auth.database }}
{{- printf "postgresql+asyncpg://%s:%s@%s:5432/%s" $user $pass $host $db }}
{{- else }}
{{- fail "Either postgresql.enabled must be true or secrets.DATABASE_URL must be set." }}
{{- end }}
{{- end }}

{{/*
Construct REDIS_URL from sub-chart values when redis.enabled=true
and the user has not set secrets.REDIS_URL explicitly.
*/}}
{{- define "aetheros.redisURL" -}}
{{- if .Values.secrets.REDIS_URL }}
{{- .Values.secrets.REDIS_URL }}
{{- else if .Values.redis.enabled }}
{{- $host := printf "%s-redis-master" .Release.Name }}
{{- if .Values.redis.auth.enabled }}
{{- printf "redis://:%s@%s:6379/0" .Values.redis.auth.password $host }}
{{- else }}
{{- printf "redis://%s:6379/0" $host }}
{{- end }}
{{- else }}
{{- fail "Either redis.enabled must be true or secrets.REDIS_URL must be set." }}
{{- end }}
{{- end }}

{{/*
Resolved image tag: uses .Values.image.tag when set, otherwise .Chart.AppVersion.
*/}}
{{- define "aetheros.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion }}
{{- end }}
