"""AetherOS Layer 8 — Chaos Engineering Generator.

Generates LitmusChaos experiment manifests (ChaosEngine YAMLs), RBAC,
schedules, and a structured Markdown test plan.  All output is deterministic
template-based generation — no LLM calls required.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def generate_pod_delete_experiment(service_name: str, slug: str, namespace: str) -> str:
    """Return LitmusChaos ChaosEngine YAML for a pod-delete experiment.

    Tests that the service recovers within 30 s when a pod is forcibly deleted
    (simulates a node crash or OOMKill event).
    """
    return f"""\
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: {service_name}-pod-delete
  namespace: {namespace}
spec:
  appinfo:
    appns: {namespace}
    applabel: "app={service_name}"
    appkind: deployment
  annotationCheck: "false"
  engineState: "active"
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-delete
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "30"
            - name: CHAOS_INTERVAL
              value: "10"
            - name: FORCE
              value: "false"
            - name: TARGET_PODS
              value: ""
            - name: PODS_AFFECTED_PERC
              value: "50"
        probe:
          - name: healthcheck-probe
            type: httpProbe
            httpProbe/inputs:
              url: "http://{service_name}.{namespace}.svc.cluster.local:8000/health"
              insecureSkipVerify: false
              method:
                get:
                  criteria: "=="
                  responseCode: "200"
            mode: Continuous
            runProperties:
              probeTimeout: 5
              interval: 5
              retry: 3
"""


def generate_network_partition_experiment(service_name: str, slug: str, namespace: str) -> str:
    """Return LitmusChaos ChaosEngine YAML for a pod-network-partition experiment.

    Tests that the service continues to serve requests with a degraded (not zero)
    success rate when network connectivity is interrupted for 60 s.
    """
    return f"""\
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: {service_name}-network-partition
  namespace: {namespace}
spec:
  appinfo:
    appns: {namespace}
    applabel: "app={service_name}"
    appkind: deployment
  annotationCheck: "false"
  engineState: "active"
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-network-partition
      spec:
        components:
          env:
            - name: NETWORK_INTERFACE
              value: "eth0"
            - name: TOTAL_CHAOS_DURATION
              value: "60"
            - name: DESTINATION_IPS
              value: ""
            - name: DESTINATION_HOSTS
              value: ""
            - name: POLICY
              value: "egress"
        probe:
          - name: latency-probe
            type: cmdProbe
            cmdProbe/inputs:
              command: >
                curl -s -o /dev/null -w "%{{http_code}}"
                http://{service_name}.{namespace}.svc.cluster.local:8000/health
              comparator:
                type: string
                criteria: "=="
                value: "200"
            mode: Continuous
            runProperties:
              probeTimeout: 10
              interval: 10
              retry: 2
"""


def generate_cpu_hog_experiment(service_name: str, slug: str, namespace: str) -> str:
    """Return LitmusChaos ChaosEngine YAML for a pod-cpu-hog experiment.

    Tests that the HPA detects the spike and scales the deployment within the
    stabilization window (30 s scale-up), verifying the autoscaler is wired.
    """
    return f"""\
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: {service_name}-cpu-hog
  namespace: {namespace}
spec:
  appinfo:
    appns: {namespace}
    applabel: "app={service_name}"
    appkind: deployment
  annotationCheck: "false"
  engineState: "active"
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-cpu-hog
      spec:
        components:
          env:
            - name: CPU_CORES
              value: "1"
            - name: TOTAL_CHAOS_DURATION
              value: "60"
            - name: TARGET_PODS
              value: ""
            - name: PODS_AFFECTED_PERC
              value: "50"
        probe:
          - name: hpa-scale-probe
            type: k8sProbe
            k8sProbe/inputs:
              group: autoscaling
              version: v2
              resource: horizontalpodautoscalers
              namespace: {namespace}
              resourceNames: "{service_name}-hpa"
              fieldSelector: "status.currentReplicas>1"
              operation: present
            mode: EOT
            runProperties:
              probeTimeout: 90
              interval: 15
              retry: 5
"""


def generate_litmus_rbac(namespace: str) -> str:
    """Return YAML for LitmusChaos ServiceAccount + ClusterRole + ClusterRoleBinding.

    Uses the litmus-admin account name expected by all ChaosEngine manifests
    generated by this module.
    """
    return f"""\
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: litmus-admin
  namespace: {namespace}
  labels:
    app.kubernetes.io/managed-by: AetherOS
    component: litmus-rbac
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: litmus-admin-{namespace}
  labels:
    app.kubernetes.io/managed-by: AetherOS
rules:
  - apiGroups: ["", "apps", "batch", "extensions"]
    resources:
      - pods
      - deployments
      - replicasets
      - statefulsets
      - daemonsets
      - jobs
      - configmaps
      - secrets
      - services
      - events
      - nodes
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete", "deletecollection"]
  - apiGroups: ["litmuschaos.io"]
    resources:
      - chaosengines
      - chaosexperiments
      - chaosresults
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: litmus-admin-{namespace}
  labels:
    app.kubernetes.io/managed-by: AetherOS
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: litmus-admin-{namespace}
subjects:
  - kind: ServiceAccount
    name: litmus-admin
    namespace: {namespace}
"""


def generate_chaos_schedule(slug: str, services: List[str], namespace: str) -> str:
    """Return LitmusChaosSchedule YAML that runs pod-delete weekly on Sunday 02:00 UTC.

    One schedule entry per service so individual services can be paused/skipped
    independently without touching the others.
    """
    schedule_entries = "\n".join(
        f"""\
  - name: {svc}-weekly-pod-delete
    spec:
      schedule:
        cron: "0 2 * * 0"
      engineTemplateSpec:
        appinfo:
          appns: {namespace}
          applabel: "app={svc}"
          appkind: deployment
        chaosServiceAccount: litmus-admin
        experiments:
          - name: pod-delete
            spec:
              components:
                env:
                  - name: TOTAL_CHAOS_DURATION
                    value: "30"
                  - name: CHAOS_INTERVAL
                    value: "10"
                  - name: FORCE
                    value: "false"
"""
        for svc in services
    )
    return f"""\
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosSchedule
metadata:
  name: {slug}-weekly-chaos
  namespace: {namespace}
spec:
  schedule:
    repeat:
      properties:
        minChaosInterval: "168h"  # 1 week
  concurrencyPolicy: Forbid
  scheduleList:
{schedule_entries}
"""


def generate_chaos_test_plan(slug: str, entities: List[dict], namespace: str) -> str:
    """Return a Markdown chaos test plan covering all entity services.

    Each service gets three scenarios: pod-delete, network-partition, cpu-hog.
    Includes hypothesis, experiment reference, expected outcome, and rollback.
    """
    lines = [
        f"# Chaos Test Plan — {slug}",
        "",
        "Generated by AetherOS Layer 8 Chaos Engineering Generator.  "
        "Run experiments in a staging namespace first; promote to production "
        "only after all hypotheses are validated.",
        "",
        f"**Namespace:** `{namespace}`  ",
        "**Tool:** [LitmusChaos](https://litmuschaos.io/) v3.x  ",
        "**Schedule:** Weekly (Sunday 02:00 UTC) via `chaos-schedule.yaml`",
        "",
        "---",
        "",
    ]

    for entity in entities:
        svc = entity.get("table", "service").replace("_", "-")
        lines += [
            f"## Service: `{svc}`",
            "",
            "### Experiment 1 — Pod Delete",
            "",
            f"- **Hypothesis:** If a `{svc}` pod is deleted, the Deployment controller "
            "recreates it and the service recovers within 30 s.",
            f"- **Experiment file:** `experiments/{svc}-pod-delete.yaml`",
            "- **Expected outcome:**",
            "  - p99 latency stays under 500 ms during recovery window",
            "  - Error rate stays under 1% (circuit breaker absorbs the spike)",
            "  - Pod count returns to desired replicas within 60 s",
            "- **Rollback:** `kubectl rollout undo deployment/" + svc + " -n " + namespace + "`",
            "",
            "### Experiment 2 — Network Partition",
            "",
            f"- **Hypothesis:** If outbound network traffic from `{svc}` is blocked for "
            "60 s, the service continues to serve cached/degraded responses instead of "
            "returning 5xx errors.",
            f"- **Experiment file:** `experiments/{svc}-network-partition.yaml`",
            "- **Expected outcome:**",
            "  - Success rate >= 95% throughout the partition window",
            "  - Upstream dependencies show retries in logs but no hard failures",
            "  - Zero data corruption after partition heals",
            "- **Rollback:** `kubectl exec` into affected pod and `ip route flush`; "
            "or `kubectl rollout restart deployment/" + svc + "`",
            "",
            "### Experiment 3 — CPU Hog",
            "",
            f"- **Hypothesis:** If CPU on `{svc}` pods is saturated for 60 s, the HPA "
            "detects the spike and scales out within the 30 s stabilisation window.",
            f"- **Experiment file:** `experiments/{svc}-cpu-hog.yaml`",
            "- **Expected outcome:**",
            "  - HPA `currentReplicas` increases within 90 s of experiment start",
            "  - p95 latency stays under 1 s after scale-out completes",
            "  - Replicas return to baseline within 5 min after experiment ends "
            "(scaleDown.stabilizationWindowSeconds=300)",
            "- **Rollback:** `kubectl scale deployment/" + svc + " --replicas=<original> "
            "-n " + namespace + "`",
            "",
            "---",
            "",
        ]

    lines += [
        "## Observability Checklist",
        "",
        "Before running any experiment, confirm:",
        "",
        "- [ ] Prometheus is scraping all pods in the namespace",
        "- [ ] Grafana dashboard shows p99 latency and error rate panels",
        "- [ ] Alertmanager is configured with a silence for the experiment window",
        "- [ ] PodDisruptionBudget (`pdb/`) is applied to prevent total outage",
        "",
        "## References",
        "",
        "- LitmusChaos docs: https://docs.litmuschaos.io/",
        "- Chaos experiment hub: https://hub.litmuschaos.io/",
        f"- RBAC manifest: `rbac.yaml` (namespace: `{namespace}`)",
        "- Automated schedule: `chaos-schedule.yaml`",
    ]

    return "\n".join(lines) + "\n"


def generate_chaos_package(entities: List[dict], slug: str, output_dir: Path) -> Path:
    """Write a complete chaos engineering package to output_dir/chaos/.

    Creates:
      rbac.yaml
      experiments/{entity}-pod-delete.yaml       (one per entity)
      experiments/{entity}-network-partition.yaml (one per entity)
      experiments/{entity}-cpu-hog.yaml           (one per entity)
      chaos-schedule.yaml
      CHAOS_TEST_PLAN.md

    Returns the chaos/ directory path.
    """
    namespace = slug
    chaos_dir = output_dir / "chaos"
    experiments_dir = chaos_dir / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)

    services = [e.get("table", "service").replace("_", "-") for e in entities]

    try:
        (chaos_dir / "rbac.yaml").write_text(generate_litmus_rbac(namespace))
        logger.info("chaos: wrote rbac.yaml")
    except Exception as e:
        logger.warning("chaos: rbac.yaml write failed: %s", e)

    for entity in entities:
        svc = entity.get("table", "service").replace("_", "-")
        try:
            (experiments_dir / f"{svc}-pod-delete.yaml").write_text(
                generate_pod_delete_experiment(svc, slug, namespace)
            )
            (experiments_dir / f"{svc}-network-partition.yaml").write_text(
                generate_network_partition_experiment(svc, slug, namespace)
            )
            (experiments_dir / f"{svc}-cpu-hog.yaml").write_text(
                generate_cpu_hog_experiment(svc, slug, namespace)
            )
            logger.info("chaos: wrote 3 experiment manifests for service=%s", svc)
        except Exception as e:
            logger.warning("chaos: experiment write failed for %s: %s", svc, e)

    try:
        (chaos_dir / "chaos-schedule.yaml").write_text(
            generate_chaos_schedule(slug, services, namespace)
        )
        logger.info("chaos: wrote chaos-schedule.yaml")
    except Exception as e:
        logger.warning("chaos: chaos-schedule.yaml write failed: %s", e)

    try:
        (chaos_dir / "CHAOS_TEST_PLAN.md").write_text(
            generate_chaos_test_plan(slug, entities, namespace)
        )
        logger.info("chaos: wrote CHAOS_TEST_PLAN.md")
    except Exception as e:
        logger.warning("chaos: CHAOS_TEST_PLAN.md write failed: %s", e)

    return chaos_dir
