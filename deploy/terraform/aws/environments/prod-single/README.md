# prod-single: the first production install

The proven testbed shape made permanent: one Docker host running the compose stack, RDS PostgreSQL 15 (pgvector), and an
off-site backup bucket. Reached on a fixed Elastic IP with a free HTTPS name `<ip-with-dashes>.sslip.io` (Let's Encrypt,
renewed by cron). Use it until there is a domain; then move to `../staging` / `../production` (load balancers, ACM wildcard
certificate for per-run preview hosts, Multi-AZ).

Live since 22 Nov 2026 in `ap-southeast-2` (the organisation's service control policy allowed only Sydney at the time).
The target region is Mumbai (`ap-south-1`): once the policy allows it, `terraform apply -var region=ap-south-1` in a fresh
state, run `bootstrap.sh`, restore the database with `scripts/restore_drill.py` from the Sydney backup, then destroy Sydney.

## What it creates

| Resource | Setting |
|---|---|
| EC2 host | m7i-flex.large, Amazon Linux 2023, encrypted 60 GB gp3, IMDSv2 with hop limit 1 (containers cannot reach instance credentials), SSM only (no SSH) |
| Security group | inbound 80 and 443 only |
| Elastic IP | fixed public address |
| RDS | PostgreSQL 15, db.t4g.small, encrypted, not public, reachable from the host only, 7-day point-in-time restore, deletion protection, final snapshot on delete, password managed by Secrets Manager |
| S3 | backups bucket, versioned, encrypted, public access blocked, 30-day expiry |
| IAM | host role: SSM core, its own backups bucket, the RDS password secret, `/<name>/*` parameters |
| Budget | monthly alert at 50/80/100 percent of `budget_usd` (default 200) when `budget_email` is set |

## Install

```bash
terraform init && terraform apply                      # terraform.tfvars: budget_email, region
aws ssm put-parameter --name /aetheros-prod/admin-password --type SecureString --value '<strong password>'
aws ssm put-parameter --name /aetheros-prod/nvidia-api-key --type SecureString --value '<model provider key>'
git -C <aether_os> archive -o aether_os.tgz main && aws s3 cp aether_os.tgz s3://<backups_bucket>/src/aether_os.tgz
git -C <velaris>   archive -o velaris.tgz   main && aws s3 cp velaris.tgz   s3://<backups_bucket>/src/velaris.tgz
sed -e "s|__DBHOST__|$(terraform output -raw db_endpoint)|" \
    -e "s|__DBSECRET__|$(terraform output -raw db_password_secret_arn)|" bootstrap.sh > /tmp/bootstrap.sh
# run /tmp/bootstrap.sh as root on the host (aws ssm send-command ... AWS-RunShellScript), then:
./scripts/smoke_test.sh https://<ip-with-dashes>.sslip.io/api admin@aetheros.ai '<admin password>'
```

`bootstrap.sh` writes `.env` with fresh random secrets, points the API and migrations at RDS through
`docker-compose.override.yml`, applies the sandbox host firewall, builds the sandbox and Velaris images, starts the stack,
and puts the front end in place. By default that is `FRONT=caddy` (`deploy/sslip`): Caddy on 80/443 with on-demand
certificates for per-run preview hosts and `velaris.<host>` for the Velaris public app, nginx behind it on loopback.
`FRONT=nginx` keeps the original single-nginx front (certbot certificate for `<host>` and `preview.<host>` only).

## Known limits

* Per-run preview certificates are issued on demand (Let's Encrypt rate limits apply: about 50 new certificates per
  week per registered name). A real domain with a DNS-01 wildcard removes that limit (KAN-75).
* One host: a host failure is an outage until a new host is bootstrapped (RDS keeps the data). Restore steps:
  `docs/ops/RUNBOOKS.md`.
* The model provider is the OpenAI-compatible NVIDIA endpoint until Bedrock access is granted on the account.
