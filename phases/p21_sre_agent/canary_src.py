"""Source text of the generated sre/canary_runner.py (placeholders __APP__ and __NS__).

A real canary: the stable Deployment is never touched until the canary has proven itself.
  1. a second Deployment <app>-canary runs the new image next to the stable one; the Service
     selects both by the shared `app` label, so traffic splits by pod count (CANARY_WEIGHT %);
  2. metrics are read for the canary pods only; MISSING DATA IS A FAILURE (no traffic, no
     Prometheus, no series all mean "not proven");
  3. promote = set the image on the stable Deployment and wait for its rollout, then delete the
     canary; rollback = delete the canary (stable never changed).
No kubectl: python:3.12-slim has none, so the Kubernetes API is called with the pod's token.
Needs get/create/patch/delete on deployments in the namespace.
"""

CANARY_SRC = '''\
#!/usr/bin/env python3
"""SRE canary runner for __APP__: canary Deployment, metric check, promote or roll back."""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Optional

import requests

logger = logging.getLogger("__APP__-canary")

APP_NAME = os.environ.get("APP_NAME", "__APP__")
NAMESPACE = os.environ.get("NAMESPACE", "__NS__")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
CANARY_WEIGHT = min(50, max(1, int(os.environ.get("CANARY_WEIGHT", "10"))))  # % of traffic
CANARY_WAIT_SECONDS = int(os.environ.get("CANARY_WAIT_SECONDS", "120"))
ROLLOUT_TIMEOUT_SECONDS = int(os.environ.get("ROLLOUT_TIMEOUT_SECONDS", "300"))
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", "5.0"))
LATENCY_THRESHOLD_MS = float(os.environ.get("LATENCY_THRESHOLD_MS", "500.0"))
CANARY_NAME = APP_NAME + "-canary"

_SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
_DEPLOY = "/apis/apps/v1/namespaces/%s/deployments" % NAMESPACE


def _k8s(method: str, path: str, body: Optional[dict] = None, patch: bool = False) -> Optional[dict]:
    """Call the Kubernetes API; None for 404, raises on other errors."""
    with open(_SA_DIR + "/token") as fh:
        token = fh.read().strip()
    ctx = ssl.create_default_context(cafile=_SA_DIR + "/ca.crt")
    ctype = "application/strategic-merge-patch+json" if patch else "application/json"
    req = urllib.request.Request(
        "https://kubernetes.default.svc" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": ctype},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def canary_replicas(stable_replicas: int, weight: int) -> int:
    """Pods for the canary so that it gets about `weight` % of the traffic (at least 1)."""
    return max(1, round(stable_replicas * weight / (100 - weight)))


def _query(query: str) -> Optional[float]:
    """Prometheus instant query -> float, or None when there is no usable value."""
    try:
        resp = requests.get(PROMETHEUS_URL + "/api/v1/query", params={"query": query}, timeout=10)
        resp.raise_for_status()
        result = resp.json().get("data", {}).get("result", [])
        value = float(result[0]["value"][1]) if result else None
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        logger.warning("prometheus query failed: %s", exc)
        return None
    return None if value is None or math.isnan(value) else value


def canary_healthy(error_rate: Optional[float], latency_ms: Optional[float]) -> bool:
    """Promote only on evidence: a missing metric is a failure, never a pass."""
    if error_rate is None or latency_ms is None:
        return False
    return error_rate <= ERROR_RATE_THRESHOLD and latency_ms <= LATENCY_THRESHOLD_MS


def _wait_ready(name: str, minimum: int) -> bool:
    deadline = time.time() + ROLLOUT_TIMEOUT_SECONDS
    while time.time() < deadline:
        dep = _k8s("GET", "%s/%s" % (_DEPLOY, name)) or {}
        status = dep.get("status", {})
        if (status.get("readyReplicas") or 0) >= minimum and status.get("updatedReplicas", 0) >= minimum:
            return True
        time.sleep(5)
    return False


def _delete_canary() -> None:
    _k8s("DELETE", "%s/%s" % (_DEPLOY, CANARY_NAME))


def run_canary(new_image: str) -> bool:
    """Run the new image beside the stable Deployment, judge it on its own metrics.

    Returns True when promoted, False when rolled back (the stable Deployment is unchanged then).
    """
    stable = _k8s("GET", "%s/%s" % (_DEPLOY, APP_NAME))
    if stable is None:
        logger.error("canary: deployment %s not found", APP_NAME)
        return False
    replicas = canary_replicas(int(stable["spec"].get("replicas") or 1), CANARY_WEIGHT)

    canary = copy.deepcopy(stable)
    canary["metadata"] = {"name": CANARY_NAME, "namespace": NAMESPACE, "labels": {"app": APP_NAME, "track": "canary"}}
    canary.pop("status", None)
    canary["spec"]["replicas"] = replicas
    canary["spec"]["selector"] = {"matchLabels": {"app": APP_NAME, "track": "canary"}}
    pod = canary["spec"]["template"]
    pod.setdefault("metadata", {}).setdefault("labels", {}).update({"app": APP_NAME, "track": "canary"})
    for container in pod["spec"]["containers"]:
        if container["name"] == APP_NAME:
            container["image"] = new_image

    _delete_canary()  # a leftover from an earlier attempt
    try:
        _k8s("POST", _DEPLOY, canary)
        if not _wait_ready(CANARY_NAME, replicas):
            logger.warning("canary: pods did not become ready in %ds — rolling back", ROLLOUT_TIMEOUT_SECONDS)
            return False
        logger.info("canary: %d pod(s) of %s serve ~%d%% of traffic, observing %ds",
                    replicas, new_image, CANARY_WEIGHT, CANARY_WAIT_SECONDS)
        time.sleep(CANARY_WAIT_SECONDS)

        sel = 'app="%s", pod=~"%s-.*"' % (APP_NAME, CANARY_NAME)
        error_rate = _query(
            'sum(rate(http_requests_total{%s, status=~"5.."}[2m])) / sum(rate(http_requests_total{%s}[2m])) * 100'
            % (sel, sel))
        latency = _query(
            "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{%s}[2m]))) * 1000" % sel)
        logger.info("canary metrics: error_rate=%s%% p95=%sms", error_rate, latency)
        if not canary_healthy(error_rate, latency):
            logger.warning("canary: not proven healthy (thresholds exceeded or no data) — rolling back")
            return False

        container = {"name": APP_NAME, "image": new_image}
        _k8s("PATCH", "%s/%s" % (_DEPLOY, APP_NAME),
             {"spec": {"template": {"spec": {"containers": [container]}}}}, patch=True)
        want = int(stable["spec"].get("replicas") or 1)
        if not _wait_ready(APP_NAME, want):
            logger.error("canary: promoted image did not roll out in %ds", ROLLOUT_TIMEOUT_SECONDS)
            _k8s("PATCH", "%s/%s" % (_DEPLOY, APP_NAME), {"spec": {"template": {"spec": {"containers": [
                {"name": APP_NAME, "image": stable["spec"]["template"]["spec"]["containers"][0]["image"]}]}}}},
                 patch=True)
            return False
        logger.info("canary: promoted %s", new_image)
        return True
    finally:
        _delete_canary()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    sys.exit(0 if run_canary(sys.argv[1]) else 1)
'''
