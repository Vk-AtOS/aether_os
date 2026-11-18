# Image builder for a GENERATED Dockerfile (core/sandbox/build_runner.py).
#
# `docker build` on the host daemon runs the RUN steps of an untrusted Dockerfile with the daemon's
# privileges and lets it name any base image or build context. The platform instead builds in this
# container: no docker socket, no privileged mode, only the run directory mounted, egress through the
# firewalled sandbox network, and the result is a tarball in the run dir that the host merely `docker load`s.
#
#   docker build -f core/sandbox/Dockerfile.builder -t aether-builder:1 core/sandbox
#
# OWNER-READY: pin the base by digest before production (the tag below is the last release we tested against):
#   docker buildx imagetools inspect gcr.io/kaniko-project/executor:v1.23.2   # copy the sha256 into the FROM line
FROM gcr.io/kaniko-project/executor:v1.23.2
# kaniko is a single static binary at /kaniko/executor and needs no other tooling.
