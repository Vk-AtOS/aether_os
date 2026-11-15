# Network: one VPC, three tiers over three AZs (public / app / data) plus an isolated sandbox tier with no route out.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

data "aws_availability_zones" "this" { state = "available" }

locals {
  azs = slice(data.aws_availability_zones.this.names, 0, 3)
  # /16 split into /20s: 0-2 public, 3-5 app, 6-8 data, 9-11 sandbox
  cidr = { for tier, base in { public = 0, app = 3, data = 6, sandbox = 9 } :
  tier => [for i in range(3) : cidrsubnet(var.vpc_cidr, 4, base + i)] }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${var.name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-igw" }
}

resource "aws_subnet" "tier" {
  for_each = { for pair in setproduct(["public", "app", "data", "sandbox"], range(3)) : "${pair[0]}-${pair[1]}" => pair }

  vpc_id                  = aws_vpc.this.id
  availability_zone       = local.azs[each.value[1]]
  cidr_block              = local.cidr[each.value[0]][each.value[1]]
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-${each.key}", Tier = each.value[0] }
}

resource "aws_eip" "nat" {
  count  = var.single_nat ? 1 : 3
  domain = "vpc"
}

resource "aws_nat_gateway" "this" {
  count         = var.single_nat ? 1 : 3
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.tier["public-${count.index}"].id
  tags          = { Name = "${var.name}-nat-${count.index}" }
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table" "app" {
  count  = 3
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.single_nat ? 0 : count.index].id
  }
  tags = { Name = "${var.name}-app-${count.index}" }
}

# data and sandbox tiers: local routes only, so neither can reach the internet or the other's subnets by route
resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-isolated" }
}

resource "aws_route_table_association" "public" {
  count          = 3
  subnet_id      = aws_subnet.tier["public-${count.index}"].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "app" {
  count          = 3
  subnet_id      = aws_subnet.tier["app-${count.index}"].id
  route_table_id = aws_route_table.app[count.index].id
}

resource "aws_route_table_association" "data" {
  count          = 3
  subnet_id      = aws_subnet.tier["data-${count.index}"].id
  route_table_id = aws_route_table.isolated.id
}

resource "aws_route_table_association" "sandbox" {
  count          = 3
  subnet_id      = aws_subnet.tier["sandbox-${count.index}"].id
  route_table_id = aws_route_table.isolated.id
}

# S3 and ECR/Logs reachable without the internet from the private tiers
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(aws_route_table.app[*].id, [aws_route_table.isolated.id])
}

# VPC flow logs: who talked to whom, kept in the log group below
resource "aws_cloudwatch_log_group" "flow" {
  name              = "/${var.name}/vpc-flow"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "flow_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow" {
  name               = "${var.name}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_assume.json
}

data "aws_iam_policy_document" "flow_write" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.flow.arn}:*"]
  }
}

resource "aws_iam_role_policy" "flow" {
  role   = aws_iam_role.flow.id
  policy = data.aws_iam_policy_document.flow_write.json
}

resource "aws_flow_log" "this" {
  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow.arn
  iam_role_arn         = aws_iam_role.flow.arn
}

# Interface endpoints so the sandbox hosts can pull their image and ship logs without any internet route.
resource "aws_security_group" "endpoints" {
  name        = "${var.name}-endpoints"
  description = "HTTPS from inside the VPC to the interface endpoints"
  vpc_id      = aws_vpc.this.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(["ecr.api", "ecr.dkr", "logs"])
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for i in range(3) : aws_subnet.tier["sandbox-${i}"].id]
  security_group_ids  = [aws_security_group.endpoints.id]
}
