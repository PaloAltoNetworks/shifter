# VPC Expansion Implementation Checklist

**Goal**: Expand from 255 to 16,384 concurrent ranges (10.1-4.0.0/16, /28 subnets)

## Phase 1: Terraform VPC Changes

### [ ] 1.1 Add Secondary CIDR Blocks
**File**: `terraform/modules/range/vpc/main.tf`
- [ ] Add after `aws_vpc` resource (around line 30):
  ```hcl
  resource "aws_vpc_ipv4_cidr_block_association" "secondary_10_2" {
    vpc_id     = aws_vpc.this.id
    cidr_block = "10.2.0.0/16"
  }

  resource "aws_vpc_ipv4_cidr_block_association" "secondary_10_3" {
    vpc_id     = aws_vpc.this.id
    cidr_block = "10.3.0.0/16"
  }

  resource "aws_vpc_ipv4_cidr_block_association" "secondary_10_4" {
    vpc_id     = aws_vpc.this.id
    cidr_block = "10.4.0.0/16"
  }
  ```

### [ ] 1.2 Update Security Group Rules
**File**: `terraform/modules/range/vpc/main.tf`
- [ ] Add to `locals` block (after line 14):
  ```hcl
  all_range_cidrs = [
    var.vpc_cidr,
    "10.2.0.0/16",
    "10.3.0.0/16",
    "10.4.0.0/16"
  ]
  ```
- [ ] Line 102: Change `cidr_blocks = [var.vpc_cidr]` → `cidr_blocks = local.all_range_cidrs`
- [ ] Line 142: Change `cidr_blocks = [var.vpc_cidr]` → `cidr_blocks = local.all_range_cidrs`
- [ ] Line 186: Change `cidr_blocks = [var.vpc_cidr]` → `cidr_blocks = local.all_range_cidrs`
- [ ] Line 216: Change `cidr_blocks = [var.vpc_cidr]` → `cidr_blocks = local.all_range_cidrs`

### [ ] 1.3 Update Network Firewall HOME_NET
**File**: `terraform/modules/range/vpc/firewall.tf`
- [ ] Line 74: Change `definition = [var.vpc_cidr]` → add all 4 CIDRs
- [ ] Line 112: Change `definition = [var.vpc_cidr]` → add all 4 CIDRs
- [ ] Line 152: Change `definition = [var.vpc_cidr]` → add all 4 CIDRs

### [ ] 1.4 Add VPC Outputs
**File**: `terraform/modules/range/vpc/outputs.tf`
- [ ] Add after line 11:
  ```hcl
  output "all_cidr_blocks" {
    description = "All CIDR blocks (primary + secondary)"
    value = concat(
      [aws_vpc.this.cidr_block],
      [
        aws_vpc_ipv4_cidr_block_association.secondary_10_2.cidr_block,
        aws_vpc_ipv4_cidr_block_association.secondary_10_3.cidr_block,
        aws_vpc_ipv4_cidr_block_association.secondary_10_4.cidr_block
      ]
    )
  }
  ```

## Phase 2: Lambda Environment Variables

### [ ] 2.1 Update Provisioner Module Variables
**File**: `terraform/modules/range/provisioner/variables.tf`
- [ ] Replace lines 42-45 (`range_cidr_prefix`) with:
  ```hcl
  variable "range_cidr_prefixes" {
    description = "List of CIDR prefixes for range subnets"
    type        = list(string)
  }

  variable "range_subnet_mask" {
    description = "Subnet mask bits (e.g., 28 for /28)"
    type        = number
    default     = 28
  }
  ```

### [ ] 2.2 Update Lambda Environment Variables
**File**: `terraform/modules/range/provisioner/main.tf`
- [ ] Replace line 70 with:
  ```hcl
  RANGE_CIDR_PREFIXES  = jsonencode(var.range_cidr_prefixes)
  RANGE_SUBNET_MASK    = tostring(var.range_subnet_mask)
  ```

### [ ] 2.3 Update Dev Portal Module Call
**File**: `terraform/environments/dev/portal/main.tf`
- [ ] Replace line 261 with:
  ```hcl
  range_cidr_prefixes = [
    for cidr in data.terraform_remote_state.range.outputs.all_cidr_blocks :
    join(".", slice(split(".", cidr), 0, 2))
  ]
  range_subnet_mask = 28
  ```

### [ ] 2.4 Update Prod Portal Module Call
**File**: `terraform/environments/prod/portal/main.tf`
- [ ] Replace line 261 with same as dev (above)

## Phase 3: Lambda Subnet Allocation Logic

### [ ] 3.1 Update Environment Variables
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Line 30-36: Update REQUIRED_ENV_VARS:
  ```python
  REQUIRED_ENV_VARS = [
      "RANGE_VPC_ID",
      "RANGE_ROUTE_TABLE_ID",
      "RANGE_CIDR_PREFIXES",  # Changed from RANGE_CIDR_PREFIX
      "RANGE_SUBNET_MASK",     # New
      "DB_HOST",
      "DB_NAME",
  ]
  ```

### [ ] 3.2 Add Helper Functions
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Add after line 37 (before `get_used_cidrs`):
  ```python
  import json

  def parse_cidr_prefixes() -> list[str]:
      """Parse RANGE_CIDR_PREFIXES from JSON environment variable."""
      return json.loads(os.environ["RANGE_CIDR_PREFIXES"])

  def calculate_subnet_cidr(subnet_index: int, cidr_prefixes: list[str], subnet_mask: int) -> tuple[str, str]:
      """
      Calculate subnet CIDR from global subnet index.
      For /28: 4,096 subnets per /16 block.
      Pattern: 10.{block}.{third_octet}.{fourth_octet}/28
      """
      subnets_per_slash24 = 2 ** (32 - 24 - subnet_mask)
      subnets_per_slash16 = 256 * subnets_per_slash24

      adjusted_index = subnet_index + 1  # Skip index 0
      block_index = adjusted_index // subnets_per_slash16
      local_index = adjusted_index % subnets_per_slash16

      if block_index >= len(cidr_prefixes):
          raise ValueError(f"Subnet index {subnet_index} exceeds capacity")

      cidr_prefix = cidr_prefixes[block_index]
      third_octet = local_index // subnets_per_slash24
      fourth_octet = (local_index % subnets_per_slash24) * (256 // subnets_per_slash24)

      return cidr_prefix, f"{cidr_prefix}.{third_octet}.{fourth_octet}/{subnet_mask}"
  ```

### [ ] 3.3 Replace get_used_cidrs()
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Replace lines 39-50 with:
  ```python
  def get_used_cidrs(ec2_client, vpc_id: str) -> set[str]:
      """Get set of CIDR blocks already in use."""
      existing_subnets = ec2_client.describe_subnets(
          Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
      )
      return {subnet["CidrBlock"] for subnet in existing_subnets["Subnets"]}
  ```

### [ ] 3.4 Delete find_available_octet()
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Delete lines 53-61 (entire function - no longer needed)

### [ ] 3.5 Replace create_subnet_with_retry()
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Replace lines 64-92 with:
  ```python
  def create_subnet_with_retry(
      ec2_client, vpc_id: str, cidr_prefixes: list[str], subnet_mask: int,
      az: str, tags: list, preferred_index: int, max_attempts: int = 250
  ) -> tuple[str, str]:
      """Create subnet with retry on conflict."""
      used_cidrs = get_used_cidrs(ec2_client, vpc_id)
      total_capacity = len(cidr_prefixes) * 256 * (2 ** (32 - 24 - subnet_mask))

      for attempt in range(max_attempts):
          candidate_index = (preferred_index + attempt) % total_capacity

          try:
              _, subnet_cidr = calculate_subnet_cidr(candidate_index, cidr_prefixes, subnet_mask)
          except ValueError as e:
              raise ValueError(f"Failed to calculate subnet: {e}")

          if subnet_cidr in used_cidrs:
              logger.warning(f"CIDR {subnet_cidr} in use, trying next")
              continue

          logger.info(f"Creating subnet {subnet_cidr}")

          try:
              response = ec2_client.create_subnet(
                  VpcId=vpc_id, CidrBlock=subnet_cidr, AvailabilityZone=az,
                  TagSpecifications=[{"ResourceType": "subnet", "Tags": tags}]
              )
              subnet_id = response["Subnet"]["SubnetId"]
              logger.info(f"Created {subnet_id}")
              return subnet_id, subnet_cidr
          except ClientError as e:
              if e.response.get("Error", {}).get("Code") == "InvalidSubnet.Conflict":
                  logger.warning(f"CIDR conflict (race), trying next")
                  used_cidrs.add(subnet_cidr)
                  continue
              raise

      raise ValueError(f"Failed after {max_attempts} attempts")
  ```

### [ ] 3.6 Update handler() Function
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`
- [ ] Lines 109-113: Replace environment variable loading:
  ```python
  range_vpc_id = get_env("RANGE_VPC_ID")
  range_route_table_id = get_env("RANGE_ROUTE_TABLE_ID")
  cidr_prefixes = parse_cidr_prefixes()  # Changed
  subnet_mask = int(get_env("RANGE_SUBNET_MASK"))  # New
  availability_zone = get_env("AVAILABILITY_ZONE", "us-east-2a")
  environment = get_env("ENVIRONMENT", "prod")

  logger.info(f"CIDR prefixes: {cidr_prefixes}, subnet mask: /{subnet_mask}")
  ```
- [ ] Lines 148-150: Update create_subnet_with_retry call:
  ```python
  subnet_id, subnet_cidr = create_subnet_with_retry(
      ec2, range_vpc_id, cidr_prefixes, subnet_mask,
      availability_zone, tags, subnet_index
  )
  ```

## Phase 4: Testing

### [ ] 4.1 Create Unit Tests
**File**: `terraform/modules/range/provisioner/lambda/tests/test_create_subnet.py` (NEW)
- [ ] Create file with tests for:
  - `calculate_subnet_cidr()` first subnet (index 0 → 10.1.0.16/28)
  - Multiple subnets in first /24
  - Transition to second /24
  - Transition to second CIDR block
  - Last possible subnet
  - Exceeds capacity error
  - `parse_cidr_prefixes()` JSON parsing

### [ ] 4.2 Integration Testing (Dev Environment)
- [ ] Apply Terraform to Range VPC
- [ ] Deploy updated Lambda
- [ ] Apply Terraform to Portal
- [ ] Create 5 test ranges sequentially
- [ ] Verify CIDR pattern: 10.1.0.16/28, 10.1.0.32/28, etc.
- [ ] Test Kali → Victim connectivity
- [ ] Create 300 ranges (exceeds old 255 limit)
- [ ] Verify ranges span multiple CIDR blocks
- [ ] Check CloudWatch logs for errors

## Phase 5: Deployment

### [ ] 5.1 Dev Deployment
- [ ] Run `terraform plan` in `terraform/environments/dev/range/`
- [ ] Review changes (3 secondary CIDR associations, SG rule changes)
- [ ] Apply Terraform to Range VPC
- [ ] Build Lambda packages: `./scripts/build-lambdas.sh`
- [ ] Run `terraform plan` in `terraform/environments/dev/portal/`
- [ ] Apply Terraform to Portal (updates Lambda env vars + code)
- [ ] Monitor initial range creations

### [ ] 5.2 Dev Validation
- [ ] Create test range, verify /28 subnet
- [ ] SSH to Kali and Victim
- [ ] Verify Kali → Victim connectivity
- [ ] Check Network Firewall logs
- [ ] Destroy test range, verify cleanup

### [ ] 5.3 Prod Deployment
- [ ] Same sequence as dev (5.1)
- [ ] Extra monitoring during first 10 range creations
- [ ] Verify no errors in CloudWatch

## Phase 6: Documentation

### [ ] 6.1 Update CLAUDE.md
- [ ] Update capacity: 255 → 16,384
- [ ] Document secondary CIDR blocks
- [ ] Update subnet allocation strategy

### [ ] 6.2 Update CHANGELOG.md
- [ ] Add entry for VPC expansion feature
- [ ] Note capacity increase and /28 subnets

## Rollback Plan (If Needed)

### [ ] Remove Secondary CIDRs
- [ ] Verify no subnets exist in 10.2-4.0.0/16 blocks
- [ ] Remove `aws_vpc_ipv4_cidr_block_association` resources
- [ ] Apply Terraform

### [ ] Revert Lambda
- [ ] Restore previous `handler.py`
- [ ] Revert environment variables to single `RANGE_CIDR_PREFIX`
- [ ] Rebuild Lambda packages
- [ ] Apply Terraform

## Quick Reference

**Capacity Calculation**:
- /28 subnets: 16 /28s per /24 range
- Each /16 block: 256 /24 ranges × 16 = 4,096 /28 subnets
- 4 blocks × 4,096 = 16,384 total capacity

**Subnet Pattern**:
- Index 0 → 10.1.0.16/28 (skip 10.1.0.0/28)
- Index 15 → 10.1.1.0/28 (first in second /24)
- Index 4096 → 10.2.0.16/28 (first in second block)
- Index 16383 → 10.4.255.240/28 (last subnet)

**Files Modified**: 9 total
- 7 Terraform files
- 1 Lambda Python file
- 1 New unit test file
