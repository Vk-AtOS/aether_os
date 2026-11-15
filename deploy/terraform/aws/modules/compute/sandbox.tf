# Sandbox hosts: plain EC2 with Docker, in the isolated subnets. No instance profile beyond what ECR pulls and EFS need,
# IMDSv2 only with hop limit 1 (containers cannot reach instance metadata), no internet route.

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sandbox" {
  name               = "${var.name}-sandbox-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "sandbox_ecr" {
  role       = aws_iam_role.sandbox.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "sandbox" {
  name = "${var.name}-sandbox-host"
  role = aws_iam_role.sandbox.name
}

resource "aws_launch_template" "sandbox" {
  name_prefix            = "${var.name}-sandbox-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = var.sandbox_instance_type
  vpc_security_group_ids = [aws_security_group.sandbox.id]
  iam_instance_profile { name = aws_iam_instance_profile.sandbox.name }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 100
      volume_type = "gp3"
      encrypted   = true
      kms_key_id  = var.kms_key_arn
    }
  }

  # Docker with TLS on 2376 needs server/CA certificates from a secret: the owner creates them (docs/ops/RUNBOOKS.md,
  # "Sandbox hosts"). Until then the daemon listens on the unix socket only and the API cannot reach it (fails closed).
  user_data = base64encode(templatefile("${path.module}/sandbox-userdata.sh.tpl", {
    efs_id  = aws_efs_file_system.state.id
    region  = var.region
    image   = var.sandbox_image
    account = data.aws_caller_identity.me.account_id
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.name}-sandbox", Role = "sandbox" }
  }
}

resource "aws_autoscaling_group" "sandbox" {
  name                = "${var.name}-sandbox"
  min_size            = var.sandbox_count
  max_size            = var.sandbox_count * 3
  desired_capacity    = var.sandbox_count
  vpc_zone_identifier = var.sandbox_subnet_ids
  health_check_type   = "EC2"

  launch_template {
    id      = aws_launch_template.sandbox.id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences { min_healthy_percentage = 50 }
  }
}
