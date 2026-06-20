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
    Go controller using operator-sdk / controller-runtime Reconciler pattern.
    Sets Provisioning on create, Ready on success, Degraded on error.
    """
    kind = _pascal(entity.get("table", "Resource"))
    group = f"{slug}.aetheros.io"
    pkg_slug = slug.replace("-", "")

    return f"""\
package controllers

import (
\t"context"
\t"fmt"

\tapiv1 "k8s.io/api/core/v1"
\t"k8s.io/apimachinery/pkg/api/errors"
\tmetav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
\t"k8s.io/apimachinery/pkg/runtime"
\tctrl "sigs.k8s.io/controller-runtime"
\t"sigs.k8s.io/controller-runtime/pkg/client"
\t"sigs.k8s.io/controller-runtime/pkg/log"

\t{pkg_slug}v1alpha1 "{slug}-operator/api/v1alpha1"
)

// {kind}Reconciler reconciles a {kind} object.
type {kind}Reconciler struct {{
\tclient.Client
\tScheme *runtime.Scheme
}}

// +kubebuilder:rbac:groups={group},resources={kind.lower()}s,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups={group},resources={kind.lower()}s/status,verbs=get;update;patch
// +kubebuilder:rbac:groups={group},resources={kind.lower()}s/finalizers,verbs=update

const {kind.lower()}Finalizer = "{slug}.aetheros.io/finalizer"

func (r *{kind}Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {{
\tlog := log.FromContext(ctx)

\t// Fetch the {kind} resource
\tvar resource {pkg_slug}v1alpha1.{kind}
\tif err := r.Get(ctx, req.NamespacedName, &resource); err != nil {{
\t\tif errors.IsNotFound(err) {{
\t\t\treturn ctrl.Result{{}}, nil
\t\t}}
\t\tlog.Error(err, "Unable to fetch {kind}")
\t\treturn ctrl.Result{{}}, err
\t}}

\t// Handle deletion via finalizer
\tif resource.DeletionTimestamp != nil {{
\t\tif containsString(resource.Finalizers, {kind.lower()}Finalizer) {{
\t\t\tif err := r.handleDeletion(ctx, &resource); err != nil {{
\t\t\t\tlog.Error(err, "Deletion handler failed")
\t\t\t\treturn ctrl.Result{{}}, err
\t\t\t}}
\t\t\tresource.Finalizers = removeString(resource.Finalizers, {kind.lower()}Finalizer)
\t\t\tif err := r.Update(ctx, &resource); err != nil {{
\t\t\t\treturn ctrl.Result{{}}, err
\t\t\t}}
\t\t}}
\t\treturn ctrl.Result{{}}, nil
\t}}

\t// Add finalizer if missing
\tif !containsString(resource.Finalizers, {kind.lower()}Finalizer) {{
\t\tresource.Finalizers = append(resource.Finalizers, {kind.lower()}Finalizer)
\t\tif err := r.Update(ctx, &resource); err != nil {{
\t\t\treturn ctrl.Result{{}}, err
\t\t}}
\t}}

\t// Set Provisioning condition
\tif err := r.setCondition(ctx, &resource, "Provisioning", metav1.ConditionTrue, "Reconciling", "Resource is being reconciled"); err != nil {{
\t\tlog.Error(err, "Failed to set Provisioning condition")
\t\treturn ctrl.Result{{}}, err
\t}}

\t// Core reconcile logic — extend here with domain-specific side effects
\tif err := r.reconcileResource(ctx, &resource); err != nil {{
\t\t_ = r.setCondition(ctx, &resource, "Degraded", metav1.ConditionTrue, "ReconcileError", fmt.Sprintf("Error: %v", err))
\t\tlog.Error(err, "Reconcile resource failed")
\t\treturn ctrl.Result{{RequeueAfter: 30000000000}}, err
\t}}

\t// Mark Ready
\tif err := r.setCondition(ctx, &resource, "Ready", metav1.ConditionTrue, "Reconciled", "Resource is ready"); err != nil {{
\t\treturn ctrl.Result{{}}, err
\t}}
\tresource.Status.ObservedGeneration = resource.Generation
\tif err := r.Status().Update(ctx, &resource); err != nil {{
\t\treturn ctrl.Result{{}}, err
\t}}

\tlog.Info("{kind} reconciled", "name", req.Name)
\treturn ctrl.Result{{}}, nil
}}

func (r *{kind}Reconciler) reconcileResource(ctx context.Context, resource *{pkg_slug}v1alpha1.{kind}) error {{
\t// TODO: implement domain-specific resource management
\t_ = ctx
\t_ = resource
\treturn nil
}}

func (r *{kind}Reconciler) handleDeletion(ctx context.Context, resource *{pkg_slug}v1alpha1.{kind}) error {{
\t// TODO: implement cleanup logic for external resources
\t_ = ctx
\t_ = resource
\treturn nil
}}

func (r *{kind}Reconciler) setCondition(ctx context.Context, resource *{pkg_slug}v1alpha1.{kind}, condType string, status metav1.ConditionStatus, reason, message string) error {{
\tnow := metav1.Now()
\tcondition := apiv1.NodeCondition{{}}
\t_ = condition
\tfound := false
\tfor i, c := range resource.Status.Conditions {{
\t\tif c.Type == condType {{
\t\t\tresource.Status.Conditions[i].Status = string(status)
\t\t\tresource.Status.Conditions[i].LastTransitionTime = now.String()
\t\t\tresource.Status.Conditions[i].Reason = reason
\t\t\tresource.Status.Conditions[i].Message = message
\t\t\tfound = true
\t\t\tbreak
\t\t}}
\t}}
\tif !found {{
\t\tresource.Status.Conditions = append(resource.Status.Conditions, struct {{
\t\t\tType               string
\t\t\tStatus             string
\t\t\tLastTransitionTime string
\t\t\tReason             string
\t\t\tMessage            string
\t\t}}{{condType, string(status), now.String(), reason, message}})
\t}}
\treturn r.Status().Update(ctx, resource)
}}

func (r *{kind}Reconciler) SetupWithManager(mgr ctrl.Manager) error {{
\treturn ctrl.NewControllerManagedBy(mgr).
\t\tFor(&{pkg_slug}v1alpha1.{kind}{{}}).
\t\tComplete(r)
}}

func containsString(slice []string, s string) bool {{
\tfor _, item := range slice {{
\t\tif item == s {{
\t\t\treturn true
\t\t}}
\t}}
\treturn false
}}

func removeString(slice []string, s string) []string {{
\tvar result []string
\tfor _, item := range slice {{
\t\tif item != s {{
\t\t\tresult = append(result, item)
\t\t}}
\t}}
\treturn result
}}
"""


# ── RBAC YAML ─────────────────────────────────────────────────────────────────


def generate_rbac_yaml(slug: str, entities: List[Dict[str, Any]]) -> str:
    """ClusterRole + ClusterRoleBinding for the operator."""
    group = f"{slug}.aetheros.io"
    resource_lines: List[str] = []
    for ent in entities:
        kind = _pascal(ent.get("table", "resource"))
        plural = kind.lower() + "s"
        resource_lines.append(f"  - {plural}")

    resources_block = "\n".join(resource_lines) if resource_lines else "  - resources"

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
{resources_block.replace("s", "s/status")}
    verbs:
      - get
      - update
      - patch
  - apiGroups:
      - ""
    resources:
      - pods
      - services
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
    pkg_slug = slug.replace("-", "")
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

\t_ "{slug}-operator/api/v1alpha1"
\t"{slug}-operator/controllers"
\t{pkg_slug}v1alpha1 "{slug}-operator/api/v1alpha1"
\t"k8s.io/apimachinery/pkg/runtime"
\tutilruntime "k8s.io/apimachinery/pkg/util/runtime"
\tclientgoscheme "k8s.io/client-go/kubernetes/scheme"
\tctrl "sigs.k8s.io/controller-runtime"
\t"sigs.k8s.io/controller-runtime/pkg/healthz"
\t"sigs.k8s.io/controller-runtime/pkg/log/zap"
)

var (
\tscheme   = runtime.NewScheme()
\tsetupLog = ctrl.Log.WithName("setup")
)

func init() {{
\tutilruntime.Must(clientgoscheme.AddToScheme(scheme))
\tutilruntime.Must({pkg_slug}v1alpha1.AddToScheme(scheme))
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
\t\tMetricsBindAddress:     metricsAddr,
\t\tPort:                   9443,
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

COPY go.mod go.sum ./
RUN go mod download

COPY . .
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
