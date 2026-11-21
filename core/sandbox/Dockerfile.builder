# Image builder for a GENERATED Dockerfile (core/sandbox/build_runner.py).
#
# `docker build` on the host daemon runs the RUN steps of an untrusted Dockerfile with the daemon's
# privileges and lets it name any base image or build context. The platform instead builds in this
# container: no docker socket, no privileged mode, only the run directory mounted, egress through the
# firewalled sandbox network, and the result is a tarball in the run dir that the host merely `docker load`s.
#
#   docker build -f core/sandbox/Dockerfile.builder -t aether-builder:1 core/sandbox
#
# Pinned by tag AND digest (the multi-arch index), like every other base image (docs/ops/RUNBOOKS.md, 'Images'). To update:
#   docker buildx imagetools inspect gcr.io/kaniko-project/executor:<new tag>   # copy the Digest line into the FROM line
FROM gcr.io/kaniko-project/executor:v1.23.2@sha256:9e69fd4330ec887829c780f5126dd80edc663df6def362cd22e79bcdf00ac53f
# kaniko is a single static binary at /kaniko/executor and needs no other tooling.
