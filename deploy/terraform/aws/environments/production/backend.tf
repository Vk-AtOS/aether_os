# Remote state, one key per environment. The bucket and lock table are created once by hand (see ../../README.md) and
# passed at init time so no account detail lives in the repository:
#   terraform init -backend-config="bucket=<state bucket>" -backend-config="dynamodb_table=<lock table>" -backend-config="region=ap-south-1"
terraform {
  backend "s3" {
    key     = "aetheros/production/terraform.tfstate"
    encrypt = true
  }
}
