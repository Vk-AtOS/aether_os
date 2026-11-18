"""AetherOS Layer 8 — Capacity Planner.

Generates Kubernetes HPA, KEDA ScaledObject, PodDisruptionBudget, and
ResourceQuota manifests tuned to the domain's performance tier and traffic
profile.  All output is deterministic template-based generation.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _hpa_targets(performance_tier: str) -> dict:
    """Return CPU/memory targets and replica bounds for the given performance tier.

    Tighter CPU targets at higher tiers force earlier scale-out, preventing
    latency spikes before the queue builds up.
    """
    tiers = {
        "standard":        {"cpu": 70, "memory": 80, "min": 2,  "max": 10},
        "high_throughput": {"cpu": 60, "memory": 70, "min": 3,  "max": 50},
        "real_time":       {"cpu": 50, "memory": 60, "min": 5,  "max": 100},
        "batch":           {"cpu": 80, "memory": 85, "min": 1,  "max": 20},
    }
    return tiers.get(performance_tier, tiers["standard"])


def generate_hpa(
    service_name: str,
    slug: str,
    performance_tier: str,
    namespace: str,
) -> str:
    """Return Kubernetes HPA YAML tuned to performance_tier.

    Uses autoscaling/v2 with separate CPU and memory metrics.
    Real-time tier adds a custom request_latency_p99 metric so the HPA
    scales before CPU is exhausted (latency is the earlier signal).
    scaleDown is intentionally slow (300 s) to avoid flapping.
    """
    t = _hpa_targets(performance_tier)

    extra_metric = ""
    if performance_tier == "real_time":
        extra_metric = """\
    - type: Pods
      pods:
        metric:
          name: request_latency_p99
        target:
          type: AverageValue
          averageValue: "200m"   # 200 ms p99 target
"""

    return f"""\
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {service_name}-hpa
  namespace: {namespace}
  labels:
    app: {service_name}
    app.kubernetes.io/managed-by: AetherOS
    tier: {performance_tier}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {service_name}
  minReplicas: {t["min"]}
  maxReplicas: {t["max"]}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {t["cpu"]}
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: {t["memory"]}
{extra_metric}\
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 4
          periodSeconds: 60
        - type: Percent
          value: 100
          periodSeconds: 60
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 2
          periodSeconds: 120
      selectPolicy: Min
"""


def generate_keda_scaledobject(
    service_name: str,
    slug: str,
    performance_tier: str,
    message_queue: str,
    namespace: str,
) -> str:
    """Return KEDA ScaledObject YAML.

    Uses a Kafka trigger when message_queue=="kafka" (event-driven scale-to-zero
    when the consumer lag is zero).  Falls back to a CPU trigger for all other
    queue types so the ScaledObject is always valid.
    """
    t = _hpa_targets(performance_tier)
    cooldown = 60 if performance_tier == "real_time" else 300

    if message_queue == "kafka":
        trigger = f"""\
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka.{namespace}.svc.cluster.local:9092
        consumerGroup: {service_name}-consumer
        topic: {service_name}-events
        lagThreshold: "50"
        offsetResetPolicy: latest
"""
    else:
        # CPU-based fallback — still useful to co-locate with HPA for visibility
        trigger = f"""\
  triggers:
    - type: cpu
      metricType: Utilization
      metadata:
        value: "{t["cpu"]}"
"""

    return f"""\
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {service_name}-scaledobject
  namespace: {namespace}
  labels:
    app: {service_name}
    app.kubernetes.io/managed-by: AetherOS
spec:
  scaleTargetRef:
    name: {service_name}
  pollingInterval: 30
  cooldownPeriod: {cooldown}
  minReplicaCount: {t["min"]}
  maxReplicaCount: {t["max"]}
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: {cooldown}
{trigger}
"""


def generate_pdb(service_name: str, namespace: str, performance_tier: str = "standard") -> str:
    """Return PodDisruptionBudget YAML.

    real_time services keep 67% of pods available (2/3 minimum) during node
    drains.  All other tiers allow one pod down at a time: a percentage minAvailable on a
    one-replica service (the batch tier) rounds up to 1 and blocks every node drain forever.
    """
    budget = ('minAvailable: "67%"' if performance_tier == "real_time" else "maxUnavailable: 1")

    return f"""\
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {service_name}-pdb
  namespace: {namespace}
  labels:
    app: {service_name}
    app.kubernetes.io/managed-by: AetherOS
spec:
  {budget}
  selector:
    matchLabels:
      app: {service_name}
"""


def generate_resource_quotas(
    slug: str,
    namespace: str,
    performance_tier: str,
) -> str:
    """Return ResourceQuota + LimitRange YAML for the namespace.

    Quota limits prevent a runaway deployment from consuming all cluster
    resources.  LimitRange ensures containers that omit resource fields still
    get safe defaults instead of inheriting node limits.
    """
    tier_quotas = {
        "standard":        {"pods": "50",  "cpu": "20",   "memory": "40Gi",  "storage": "200Gi"},
        "high_throughput": {"pods": "200", "cpu": "100",  "memory": "200Gi", "storage": "500Gi"},
        "real_time":       {"pods": "500", "cpu": "200",  "memory": "400Gi", "storage": "1Ti"},
        "batch":           {"pods": "100", "cpu": "50",   "memory": "100Gi", "storage": "2Ti"},
    }
    tier_limits = {
        "standard":        {"cpu_req": "100m", "mem_req": "128Mi", "cpu_lim": "1",    "mem_lim": "1Gi"},
        "high_throughput": {"cpu_req": "250m", "mem_req": "256Mi", "cpu_lim": "2",    "mem_lim": "2Gi"},
        "real_time":       {"cpu_req": "500m", "mem_req": "512Mi", "cpu_lim": "4",    "mem_lim": "4Gi"},
        "batch":           {"cpu_req": "100m", "mem_req": "256Mi", "cpu_lim": "8",    "mem_lim": "8Gi"},
    }
    q = tier_quotas.get(performance_tier, tier_quotas["standard"])
    lim = tier_limits.get(performance_tier, tier_limits["standard"])

    return f"""\
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {slug}-quota
  namespace: {namespace}
  labels:
    app.kubernetes.io/managed-by: AetherOS
    tier: {performance_tier}
spec:
  hard:
    pods: "{q["pods"]}"
    requests.cpu: "{q["cpu"]}"
    requests.memory: "{q["memory"]}"
    limits.cpu: "{q["cpu"]}"
    limits.memory: "{q["memory"]}"
    persistentvolumeclaims: "20"
    requests.storage: "{q["storage"]}"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: {slug}-limitrange
  namespace: {namespace}
  labels:
    app.kubernetes.io/managed-by: AetherOS
spec:
  limits:
    - type: Container
      default:
        cpu: "{lim["cpu_lim"]}"
        memory: "{lim["mem_lim"]}"
      defaultRequest:
        cpu: "{lim["cpu_req"]}"
        memory: "{lim["mem_req"]}"
      max:
        cpu: "{lim["cpu_lim"]}"
        memory: "{lim["mem_lim"]}"
"""


def generate_capacity_package(
    entities: List[dict],
    slug: str,
    output_dir: Path,
    performance_tier: str,
    message_queue: str,
) -> Path:
    """Write a complete capacity planning package to output_dir/capacity/.

    Creates:
      hpa/{entity}-hpa.yaml              (one per entity, when there is no message queue)
      keda/{entity}-scaledobject.yaml    (one per entity, when there is a message queue; replaces the HPA)
      pdb/{entity}-pdb.yaml              (one per entity)
      resource-quotas.yaml

    Returns the capacity/ directory path.
    """
    namespace = slug
    capacity_dir = output_dir / "capacity"
    hpa_dir = capacity_dir / "hpa"
    keda_dir = capacity_dir / "keda"
    pdb_dir = capacity_dir / "pdb"

    for d in (hpa_dir, keda_dir, pdb_dir):
        d.mkdir(parents=True, exist_ok=True)

    for entity in entities:
        svc = entity.get("table", "service").replace("_", "-")
        # KEDA creates and owns an HPA for the Deployment it scales; a second, standalone
        # HPA on the same target makes the two controllers fight. One scaler per service.
        if message_queue:
            try:
                (keda_dir / f"{svc}-scaledobject.yaml").write_text(
                    generate_keda_scaledobject(svc, slug, performance_tier, message_queue, namespace)
                )
                logger.info("capacity: wrote KEDA ScaledObject for service=%s", svc)
            except Exception as e:
                logger.warning("capacity: KEDA write failed for %s: %s", svc, e)
        else:
            try:
                (hpa_dir / f"{svc}-hpa.yaml").write_text(
                    generate_hpa(svc, slug, performance_tier, namespace)
                )
                logger.info("capacity: wrote HPA for service=%s", svc)
            except Exception as e:
                logger.warning("capacity: HPA write failed for %s: %s", svc, e)

        try:
            (pdb_dir / f"{svc}-pdb.yaml").write_text(
                generate_pdb(svc, namespace, performance_tier)
            )
            logger.info("capacity: wrote PDB for service=%s", svc)
        except Exception as e:
            logger.warning("capacity: PDB write failed for %s: %s", svc, e)

    try:
        (capacity_dir / "resource-quotas.yaml").write_text(
            generate_resource_quotas(slug, namespace, performance_tier)
        )
        logger.info("capacity: wrote resource-quotas.yaml")
    except Exception as e:
        logger.warning("capacity: resource-quotas.yaml write failed: %s", e)

    return capacity_dir
