output "vpc_id" { value = aws_vpc.this.id }
output "vpc_cidr" { value = aws_vpc.this.cidr_block }
output "public_subnet_ids" { value = [for i in range(3) : aws_subnet.tier["public-${i}"].id] }
output "app_subnet_ids" { value = [for i in range(3) : aws_subnet.tier["app-${i}"].id] }
output "data_subnet_ids" { value = [for i in range(3) : aws_subnet.tier["data-${i}"].id] }
output "sandbox_subnet_ids" { value = [for i in range(3) : aws_subnet.tier["sandbox-${i}"].id] }
