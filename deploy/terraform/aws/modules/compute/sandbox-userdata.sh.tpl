#!/bin/bash
# Sandbox host bootstrap. Idempotent enough to re-run; logs to /var/log/sandbox-bootstrap.log
set -euo pipefail
exec > >(tee /var/log/sandbox-bootstrap.log) 2>&1
dnf install -y docker amazon-efs-utils
mkdir -p /home/aether/.aether_os
mount -t efs -o tls,accesspoint=none ${efs_id}:/aether /home/aether/.aether_os || echo "EFS mount failed: check the access point and security groups"
echo "${efs_id}:/aether /home/aether/.aether_os efs _netdev,tls 0 0" >> /etc/fstab
systemctl enable --now docker
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${account}.dkr.ecr.${region}.amazonaws.com || true
docker pull ${image} || echo "image pull failed: ${image}"
