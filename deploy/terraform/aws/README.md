# Terraform for AWS (default cloud module, KAN-48)

Region `ap-south-1` (Mumbai). Written to `docs/ops/CLOUD_REFERENCE_ARCHITECTURE.md`. The cloud choice is still the owner's
(KAN-77); this is the default until then. **Never `apply` without owner approval.** Nothing here has been planned or applied
against a real account.

Layout: `modules/{network,data,compute,edge,observability}` composed by `modules/stack`; one root per environment in
`environments/{staging,production}`, each with its own state key. Staging is smaller (single NAT, single-AZ database, one API task).

What it creates: VPC with public / app / data / sandbox tiers (data and sandbox have no internet route; interface endpoints for
ECR and logs), RDS Postgres 15, ElastiCache Redis 7 (`noeviction`, AUTH, TLS), SQS queue + dead-letter queue, two S3 buckets
(artifacts; backups with object lock), Secrets Manager entries, KMS key, ECS Fargate services (API, preview, Velaris API, Velaris
public) with a rolling deployment circuit breaker, two ALBs, EFS for run state, an Auto Scaling group of Docker hosts for
sandboxes, ACM certificates (the preview one is a wildcard), Route 53 records, CloudWatch alarms and an SNS topic.

## Use

    # once, by hand: a state bucket (versioned, encrypted) and a DynamoDB lock table; hosted zones for the app and preview domains
    cd deploy/terraform/aws/environments/staging
    cp terraform.tfvars.example terraform.tfvars        # fill in; it is git-ignored
    terraform init -backend-config="bucket=..." -backend-config="dynamodb_table=..." -backend-config="region=ap-south-1"
    terraform validate && terraform plan -out plan.out  # review with the owner
    # terraform apply plan.out                          # ONLY with owner approval

After the first apply, fill the empty secrets (the list is `owner_supplied` in `modules/data/main.tf`), for example
`aws secretsmanager put-secret-value --secret-id aetheros-staging/ANTHROPIC_API_KEY --secret-string ...`, then force a new
deployment of the services. Generated secrets (database and Redis URLs) are written by Terraform and therefore live in the
state: keep the state bucket private, encrypted and limited to the deployers.

## Testbed (`environments/testbed`)

A throwaway environment for the tests that need real infrastructure (compose up and the kill test, restore drill, sandbox
images, pgvector, Velaris smoke): one Docker host (m7i-flex.large, no inbound port, reached with
`aws ssm start-session`), RDS PostgreSQL 15 db.t4g.micro (password in Secrets Manager), and a private S3 backup bucket. Default
VPC, local state, no domain. Region defaults to `ap-southeast-2` because the owner's test account allows no other region.
Optional budget alert: `-var budget_email=...`. Destroy it when the run is over: `terraform destroy`.

## Verified and not verified

* `terraform validate` passes for both environments (Terraform 1.9.8, AWS provider 5.x, `init -backend=false`).
* NOT verified: `plan` and `apply` (need an account), the sandbox hosts' Docker-over-TLS setup, EFS-mounted run directories
  seen by remote Docker (`AETHER_SANDBOX=docker` against a remote daemon has not been run; see KAN-66), image pull from ECR.
* Known gaps: no Azure module; no queue-depth autoscaling; WAF ACL is accepted but not created; remote state bucket is manual.
