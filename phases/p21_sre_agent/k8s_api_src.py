"""Source text of the in-cluster remediation helper inlined into generated SRE scripts.

The generated agents run in python:3.12-slim, which has no kubectl, so remediation
talks to the Kubernetes API with the pod's service-account token instead. Only the
two pre-approved actions are supported; anything else is refused (fail closed).
"""

K8S_API_SRC = '''\
import datetime
import json
import os
import shlex
import ssl
import urllib.request

_SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"


def _k8s_patch(path, body, content_type):
    with open(_SA_DIR + "/token") as fh:
        token = fh.read().strip()
    ctx = ssl.create_default_context(cafile=_SA_DIR + "/ca.crt")
    req = urllib.request.Request(
        "https://kubernetes.default.svc" + path, data=json.dumps(body).encode(), method="PATCH",
        headers={"Authorization": "Bearer " + token, "Content-Type": content_type},
    )
    urllib.request.urlopen(req, timeout=30, context=ctx).read()


def run_remediation(command):
    """Apply 'kubectl scale deployment/X --replicas=N' or 'kubectl rollout restart deployment/X'
    through the Kubernetes API. Returns True on success; raises on API errors; any other
    command raises ValueError."""
    argv = shlex.split(command)
    ns = os.environ.get("NAMESPACE", "default")
    if "-n" in argv:
        i = argv.index("-n")
        ns = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) == 4 and argv[:3] == ["kubectl", "rollout", "restart"] and argv[3].startswith("deployment/"):
        name = argv[3].split("/", 1)[1]
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _k8s_patch("/apis/apps/v1/namespaces/%s/deployments/%s" % (ns, name),
                   {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": stamp}}}}},
                   "application/strategic-merge-patch+json")
        return True
    if len(argv) == 4 and argv[:2] == ["kubectl", "scale"] and argv[2].startswith("deployment/") \\
            and argv[3].startswith("--replicas="):
        name = argv[2].split("/", 1)[1]
        replicas = int(argv[3].split("=", 1)[1])
        _k8s_patch("/apis/apps/v1/namespaces/%s/deployments/%s/scale" % (ns, name),
                   {"spec": {"replicas": replicas}}, "application/merge-patch+json")
        return True
    raise ValueError("remediation not pre-approved: " + command)
'''
