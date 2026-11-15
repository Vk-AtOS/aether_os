"""
Kubernetes Operator generator for AetherOS P17 control_plane phase.

Generates a complete operator-sdk-style Kubernetes Operator for each domain
entity, including CRD YAML, Go controllers, RBAC manifests, main.go, go.mod,
and a multi-stage Dockerfile.

Output layout (under output_dir/operator/):
  main.go
  go.mod
  Dockerfile
  controllers/{Entity}Controller.go   — one per entity
  config/crd/{entity}_crd.yaml        — one per entity
  config/rbac/role.yaml
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def _field_type_to_openapi(field_type: str) -> str:
    """Map domain IR field types to OpenAPI/CRD schema types."""
    mapping = {
        "string": "string",
        "str": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "text": "string",
        "datetime": "string",
        "date": "string",
        "email": "string",
        "uuid": "string",
    }
    return mapping.get(field_type.lower(), "string")


# ── CRD YAML ──────────────────────────────────────────────────────────────────


def generate_crd_yaml(entity: Dict[str, Any], slug: str) -> str:
    """
    Kubernetes CRD YAML for a custom resource representing a domain entity.
    Spec includes all entity fields as schema properties; status tracks lifecycle
    conditions (Provisioning, Ready, Degraded) and observedGeneration.
    """
    kind = _pascal(entity.get("table", "Resource"))
    plural = kind.lower() + "s"
    group = f"{slug}.aetheros.io"

    fields: List[Dict[str, Any]] = entity.get("fields", [])
    # Build spec properties block
    props_lines: List[str] = []
    for f in fields:
        fname = f.get("name", "field")
        ftype = _field_type_to_openapi(f.get("type", "string"))
        props_lines.append(f"                  {fname}:")
        props_lines.append(f"                    type: {ftype}")
    props_block = "\n".join(props_lines) if props_lines else "                  {}"

    return f"""\
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: {plural}.{group}
spec:
  group: {group}
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
{props_block}
            status:
              type: object
              properties:
                phase:
                  type: string
                observedGeneration:
                  type: integer
                  format: int64
                conditions:
                  type: array
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                      status:
                        type: string
                      lastTransitionTime:
                        type: string
                      reason:
                        type: string
                      message:
                        type: string
      subresources:
        status: {{}}
  scope: Namespaced
  names:
    plural: {plural}
    singular: {kind.lower()}
    kind: {kind}
    shortNames:
      - {kind.lower()[:4]}
"""


# ── Go controller ─────────────────────────────────────────────────────────────


def generate_controller_go(entity: Dict[str, Any], slug: str) -> str:
    """
    Go controller (controller-runtime) for one entity kind.

    Works on unstructured objects, so no typed API package (api/v1alpha1) has to exist or be
    code-generated: the operator compiles from the generated files alone. Reconcile validates
    the spec (required fields), then records status.phase, the Ready/Degraded conditions and
    observedGeneration. A spec error is permanent: Degraded, no retry loop until the object changes.
    """
    kind = _pascal(entity.get("table", "Resource"))
    required = [str(f["name"]) for f in entity.get("fields", []) if f.get("required") and f.get("name")]
    required_go = ", ".join('"%s"' % r.replace("\\", "").replace('"', "") for r in required)
    return (
        _CONTROLLER_GO.replace("__KIND__", kind)
        .replace("__GROUP__", f"{slug}.aetheros.io")
        .replace("__PLURAL__", kind.lower() + "s")
        .replace("__REQUIRED__", required_go)
    )


_CONTROLLER_GO = """\
package controllers

import (
\t"context"
\t"fmt"
\t"time"

\t"k8s.io/apimachinery/pkg/api/errors"
\t"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
\t"k8s.io/apimachinery/pkg/runtime"
\t"k8s.io/apimachinery/pkg/runtime/schema"
\tctrl "sigs.k8s.io/controller-runtime"
\t"sigs.k8s.io/controller-runtime/pkg/client"
\t"sigs.k8s.io/controller-runtime/pkg/log"
)

// __KIND__GVK identifies the custom resource this controller reconciles.
var __KIND__GVK = schema.GroupVersionKind{Group: "__GROUP__", Version: "v1alpha1", Kind: "__KIND__"}

// required__KIND__Fields must be present in spec.
var required__KIND__Fields = []string{__REQUIRED__}

// __KIND__Reconciler reconciles a __KIND__ object.
type __KIND__Reconciler struct {
\tclient.Client
\tScheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=__GROUP__,resources=__PLURAL__,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups=__GROUP__,resources=__PLURAL__/status,verbs=get;update;patch

func (r *__KIND__Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
\tlogger := log.FromContext(ctx)

\tobj := &unstructured.Unstructured{}
\tobj.SetGroupVersionKind(__KIND__GVK)
\tif err := r.Get(ctx, req.NamespacedName, obj); err != nil {
\t\tif errors.IsNotFound(err) {
\t\t\treturn ctrl.Result{}, nil
\t\t}
\t\treturn ctrl.Result{}, err
\t}
\tif !obj.GetDeletionTimestamp().IsZero() {
\t\treturn ctrl.Result{}, nil // nothing outside the cluster to clean up, so no finalizer
\t}

\tphase, reason, message, status := "Ready", "Reconciled", "Resource is ready", "True"
\tif err := validate__KIND__(obj); err != nil {
\t\tphase, reason, message, status = "Degraded", "InvalidSpec", err.Error(), "False"
\t\tlogger.Info("__KIND__ spec is invalid", "name", req.Name, "reason", message)
\t}

\tif err := setStatus(obj, phase, reason, message, status); err != nil {
\t\treturn ctrl.Result{}, err
\t}
\tif err := r.Status().Update(ctx, obj); err != nil {
\t\tif errors.IsConflict(err) {
\t\t\treturn ctrl.Result{RequeueAfter: time.Second}, nil
\t\t}
\t\treturn ctrl.Result{}, err
\t}
\tlogger.Info("__KIND__ reconciled", "name", req.Name, "phase", phase)
\treturn ctrl.Result{}, nil
}

func validate__KIND__(obj *unstructured.Unstructured) error {
\tfor _, field := range required__KIND__Fields {
\t\tif _, found, _ := unstructured.NestedFieldNoCopy(obj.Object, "spec", field); !found {
\t\t\treturn fmt.Errorf("spec.%s is required", field)
\t\t}
\t}
\treturn nil
}

func (r *__KIND__Reconciler) SetupWithManager(mgr ctrl.Manager) error {
\tu := &unstructured.Unstructured{}
\tu.SetGroupVersionKind(__KIND__GVK)
\treturn ctrl.NewControllerManagedBy(mgr).For(u).Complete(r)
}
"""


# One copy for the whole package: every controller calls it, so it cannot live in a per-kind file.
STATUS_GO = """\
package controllers

import (
\t"time"

\t"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// setStatus writes phase, observedGeneration and the Ready condition (status "True" or "False").
func setStatus(obj *unstructured.Unstructured, phase, reason, message, status string) error {
\tnow := time.Now().UTC().Format(time.RFC3339)
\tcondition := map[string]interface{}{
\t\t"type": "Ready", "status": status, "reason": reason, "message": message, "lastTransitionTime": now,
\t}
\told, _, _ := unstructured.NestedSlice(obj.Object, "status", "conditions")
\tconditions := []interface{}{}
\tfor _, c := range old {
\t\tm, ok := c.(map[string]interface{})
\t\tif !ok || m["type"] == "Ready" {
\t\t\tif ok && m["status"] == status {
\t\t\t\tcondition["lastTransitionTime"] = m["lastTransitionTime"] // unchanged status keeps its time
\t\t\t}
\t\t\tcontinue
\t\t}
\t\tconditions = append(conditions, m)
\t}
\tconditions = append(conditions, condition)
\tif err := unstructured.SetNestedSlice(obj.Object, conditions, "status", "conditions"); err != nil {
\t\treturn err
\t}
\tif err := unstructured.SetNestedField(obj.Object, phase, "status", "phase"); err != nil {
\t\treturn err
\t}
\treturn unstructured.SetNestedField(obj.Object, obj.GetGeneration(), "status", "observedGeneration")
}
"""


# ── RBAC YAML ─────────────────────────────────────────────────────────────────


def generate_rbac_yaml(slug: str, entities: List[Dict[str, Any]]) -> str:
    """ClusterRole + ClusterRoleBinding for the operator."""
    group = f"{slug}.aetheros.io"
    plurals = [_pascal(ent.get("table", "resource")).lower() + "s" for ent in entities] or ["resources"]
    # six spaces: the list sits under "resources:" inside a rule inside "rules:"
    resources_block = "\n".join(f"      - {p}" for p in plurals)
    status_block = "\n".join(f"      - {p}/status" for p in plurals)

    return f"""\
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {slug}-operator-manager-role
rules:
  - apiGroups:
      - {group}
    resources:
{resources_block}
    verbs:
      - get
      - list
      - watch
      - update
      - patch
  - apiGroups:
      - {group}
    resources:
{status_block}
    verbs:
      - get
      - update
      - patch
  - apiGroups:
      - ""
    resources:
      - pods
      - services
    verbs:
      - get
      - list
      - watch
  - apiGroups:
      - apps
    resources:
      - deployments
    verbs:
      - get
      - list
      - watch
  - apiGroups:
      - ""
    resources:
      - events
    verbs:
      - create
      - update
      - patch
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {slug}-operator-manager-rolebinding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {slug}-operator-manager-role
subjects:
  - kind: ServiceAccount
    name: {slug}-operator-controller-manager
    namespace: {slug}-system
"""


# ── main.go ───────────────────────────────────────────────────────────────────


def generate_main_go(slug: str, entities: List[Dict[str, Any]]) -> str:
    """Operator main.go: registers all controllers and starts the manager."""
    controller_setups: List[str] = []
    for ent in entities:
        kind = _pascal(ent.get("table", "resource"))
        controller_setups.append(
            f"""\tif err = (&controllers.{kind}Reconciler{{
\t\tClient: mgr.GetClient(),
\t\tScheme: mgr.GetScheme(),
\t}}).SetupWithManager(mgr); err != nil {{
\t\tsetupLog.Error(err, "unable to create controller", "controller", "{kind}")
\t\tos.Exit(1)
\t}}"""
        )
    setup_block = "\n\n".join(controller_setups) if controller_setups else "\t// no entities"

    return f"""\
package main

import (
\t"flag"
\t"os"

\t"{slug}-operator/controllers"
\t"k8s.io/apimachinery/pkg/runtime"
\tutilruntime "k8s.io/apimachinery/pkg/util/runtime"
\tclientgoscheme "k8s.io/client-go/kubernetes/scheme"
\tctrl "sigs.k8s.io/controller-runtime"
\t"sigs.k8s.io/controller-runtime/pkg/healthz"
\t"sigs.k8s.io/controller-runtime/pkg/log/zap"
\tmetricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
)

var (
\tscheme   = runtime.NewScheme()
\tsetupLog = ctrl.Log.WithName("setup")
)

func init() {{
\tutilruntime.Must(clientgoscheme.AddToScheme(scheme))
}}

func main() {{
\tvar metricsAddr string
\tvar enableLeaderElection bool
\tvar probeAddr string

\tflag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "The address the metric endpoint binds to.")
\tflag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "The address the probe endpoint binds to.")
\tflag.BoolVar(&enableLeaderElection, "leader-elect", false, "Enable leader election for controller manager.")
\topts := zap.Options{{Development: true}}
\topts.BindFlags(flag.CommandLine)
\tflag.Parse()

\tctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

\tmgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{{
\t\tScheme:                 scheme,
\t\tMetrics:                metricsserver.Options{{BindAddress: metricsAddr}},
\t\tHealthProbeBindAddress: probeAddr,
\t\tLeaderElection:         enableLeaderElection,
\t\tLeaderElectionID:       "{slug}.aetheros.io",
\t}})
\tif err != nil {{
\t\tsetupLog.Error(err, "unable to start manager")
\t\tos.Exit(1)
\t}}

{setup_block}

\tif err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {{
\t\tsetupLog.Error(err, "unable to set up health check")
\t\tos.Exit(1)
\t}}
\tif err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {{
\t\tsetupLog.Error(err, "unable to set up ready check")
\t\tos.Exit(1)
\t}}

\tsetupLog.Info("starting manager")
\tif err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {{
\t\tsetupLog.Error(err, "problem running manager")
\t\tos.Exit(1)
\t}}
}}
"""


# ── go.mod ────────────────────────────────────────────────────────────────────


def generate_go_mod_operator(slug: str) -> str:
    """go.mod for the operator with controller-runtime and k8s dependencies."""
    return f"""\
module {slug}-operator

go 1.21

require (
\tk8s.io/apimachinery v0.29.0
\tk8s.io/client-go v0.29.0
\tsigs.k8s.io/controller-runtime v0.17.0
)

require (
\tgithub.com/beorn7/perks v1.0.1 // indirect
\tgithub.com/go-logr/logr v1.4.1 // indirect
\tgithub.com/go-logr/zapr v1.3.0 // indirect
\tgithub.com/prometheus/client_golang v1.18.0 // indirect
\tgo.uber.org/zap v1.26.0 // indirect
\tgolang.org/x/net v0.20.0 // indirect
\tk8s.io/api v0.29.0 // indirect
\tk8s.io/klog/v2 v2.120.1 // indirect
)
"""


# ── Dockerfile ────────────────────────────────────────────────────────────────


def generate_operator_dockerfile() -> str:
    """Multi-stage Go build Dockerfile; final image is scratch (CGO_ENABLED=0)."""
    return """\
# Build stage
FROM golang:1.21-alpine AS builder
WORKDIR /workspace

# go.sum is not generated with the project: resolve it from go.mod and the sources.
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -a -o manager main.go

# Final minimal image
FROM scratch
WORKDIR /
COPY --from=builder /workspace/manager .
USER 65532:65532

ENTRYPOINT ["/manager"]
"""


# ── Package orchestrator ──────────────────────────────────────────────────────


def generate_operator_package(
    entities: List[Dict[str, Any]], slug: str, output_dir: Path
) -> Path:
    """
    Orchestrate all operator file generators and write everything under
    output_dir/operator/.

    Layout:
      operator/
        main.go
        go.mod
        Dockerfile
        controllers/{Entity}Controller.go
        config/crd/{entity}_crd.yaml
        config/rbac/role.yaml
    """
    operator_dir = output_dir / "operator"
    controllers_dir = operator_dir / "controllers"
    crd_dir = operator_dir / "config" / "crd"
    rbac_dir = operator_dir / "config" / "rbac"

    for d in (operator_dir, controllers_dir, crd_dir, rbac_dir):
        d.mkdir(parents=True, exist_ok=True)

    (operator_dir / "main.go").write_text(generate_main_go(slug, entities))
    (operator_dir / "go.mod").write_text(generate_go_mod_operator(slug))
    (controllers_dir / "status.go").write_text(STATUS_GO)
    (operator_dir / "Dockerfile").write_text(generate_operator_dockerfile())
    (rbac_dir / "role.yaml").write_text(generate_rbac_yaml(slug, entities))

    for entity in entities:
        kind = _pascal(entity.get("table", "resource"))
        table_name = entity.get("table", "resource")

        controller_code = generate_controller_go(entity, slug)
        (controllers_dir / f"{kind}Controller.go").write_text(controller_code)

        crd_yaml = generate_crd_yaml(entity, slug)
        (crd_dir / f"{table_name}_crd.yaml").write_text(crd_yaml)

    logger.info(
        "p17_control_plane: operator package written to %s (%d entities)",
        operator_dir,
        len(entities),
    )
    return operator_dir
