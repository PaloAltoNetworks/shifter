# VPC Expansion Plan: Support 1,000+ Concurrent Ranges

## Problem
Current Range VPC capacity: 255 concurrent ranges (10.1.0.0/16 with /24 subnets)
Required capacity: 1,000+ concurrent ranges for day 1

## Solution
Combine two approaches:
1. **Add 3 secondary CIDR blocks**: 10.2.0.0/16, 10.3.0.0/16, 10.4.0.0/16
2. **Use smaller subnets**: Change from /24 (256 IPs) to /28 (16 IPs, 11 usable)

## Result
- **Total capacity**: 16,384 concurrent ranges
- **Per range**: 2 VMs (Kali + Victim) in /28 subnet with 11 usable IPs
- **CIDR blocks**: 4 total (1 primary + 3 secondary)
- **Subnets per block**: 4,096 /28 subnets per /16 block

## Technical Approach

### Terraform Changes
1. **VPC Module** (`terraform/modules/range/vpc/`):
   - Add 3 `aws_vpc_ipv4_cidr_block_association` resources
   - Update security group rules to include all CIDR blocks
   - Update Network Firewall HOME_NET definitions
   - Add `all_cidr_blocks` output

2. **Provisioner Module** (`terraform/modules/range/provisioner/`):
   - Change `range_cidr_prefix` (string) to `range_cidr_prefixes` (list)
   - Add `range_subnet_mask` variable (default: 28)
   - Pass both as Lambda environment variables (JSON-encoded list)

3. **Environment Configs** (`terraform/environments/{dev,prod}/portal/`):
   - Update provisioner module call to pass list of prefixes
   - Add `range_subnet_mask = 28`

### Lambda Changes
**File**: `terraform/modules/range/provisioner/lambda/create_subnet/handler.py`

1. **New Functions**:
   - `parse_cidr_prefixes()` - Parse JSON list from env var
   - `calculate_subnet_cidr(index, prefixes, mask)` - Calculate CIDR from index
     - Handles /28 allocation across multiple /16 blocks
     - Pattern: `10.{block}.{third_octet}.{fourth_octet}/28`
     - Fourth octets: 0, 16, 32, 48, ..., 240 (16 per /24)

2. **Modified Functions**:
   - `get_used_cidrs()` - Track full CIDRs instead of just third octets
   - `create_subnet_with_retry()` - Use new calculation logic
   - `handler()` - Call new functions with updated parameters

3. **Deleted Functions**:
   - `find_available_octet()` - No longer needed

### Subnet Allocation Strategy

**Current** (255 capacity):
```
Pattern: 10.1.X.0/24
Where X = subnet_index + 1 (1-255)
```

**New** (16,384 capacity):
```
Pattern: 10.{block}.{third}.{fourth}/28

Calculation:
- subnets_per_slash24 = 16 (for /28)
- subnets_per_slash16 = 4,096 (256 /24 ranges × 16)
- block_index = (subnet_index + 1) // 4096
- local_index = (subnet_index + 1) % 4096
- third_octet = local_index // 16
- fourth_octet = (local_index % 16) × 16

Examples:
- Index 0 → 10.1.0.16/28 (skip 10.1.0.0/28 for infrastructure)
- Index 15 → 10.1.1.0/28 (first in second /24)
- Index 4096 → 10.2.0.16/28 (first in second block)
- Index 16383 → 10.4.255.240/28 (last subnet)
```

## Migration & Compatibility

### Backward Compatible
- Existing /24 ranges continue working
- Security group rules are additive (superset of old rules)
- No database schema changes needed
- Lambda handles conflicts between old /24 and new /28 subnets

### Gradual Transition
- Old ranges keep /24 subnets until destroyed
- New ranges get /28 subnets from any CIDR block
- Capacity increases as old ranges are cleaned up

## Deployment Sequence

### Phase 1: Dev Environment
1. Apply Terraform to Range VPC (adds secondary CIDRs)
2. Update Lambda code (handler.py changes)
3. Build Lambda packages: `./scripts/build-lambdas.sh`
4. Apply Terraform to Portal (updates Lambda env vars + code)
5. Test new range creation

### Phase 2: Validation
1. Create 5 test ranges sequentially
2. Verify CIDR allocation pattern
3. Test Kali ↔ Victim connectivity across CIDR blocks
4. Verify Network Firewall rules apply to all blocks
5. Create 300 ranges to exceed old 255 limit
6. Monitor CloudWatch logs for errors

### Phase 3: Production
1. Same sequence as dev after successful validation
2. Extra monitoring during first 10 range creations

## Testing Strategy

### Unit Tests
Create `terraform/modules/range/provisioner/lambda/tests/test_create_subnet.py`:
- Test CIDR calculation for various indices
- Test transition between /24 ranges
- Test transition between CIDR blocks
- Test last subnet in each block
- Test capacity exceeded error
- Test JSON parsing of CIDR prefixes

### Integration Tests
- Sequential range creation (verify pattern)
- Parallel range creation (verify conflict handling)
- Cross-CIDR connectivity (Kali in 10.1 → Victim in 10.2)
- Network Firewall rules (XDR egress, Kali blocked)
- Capacity test (300+ ranges)

## Rollback Plan

### If Issues Occur in Dev
1. **Terraform**: Remove secondary CIDR associations (only if no subnets in them)
2. **Lambda**: Revert to previous handler.py
3. **Env Vars**: Revert to single `RANGE_CIDR_PREFIX`
4. **Rebuild**: Rebuild Lambda packages with old code
5. **Apply**: Apply reverted Terraform

### Partial Rollback
- Keep secondary CIDRs attached (harmless)
- Revert Lambda to allocate only /24 in 10.1.0.0/16
- Fix issues, then re-deploy /28 logic

## Risks & Mitigation

### Low Risk
- Secondary CIDR associations are non-disruptive
- Existing ranges continue working
- Security group changes are additive (more permissive)
- VPC feature is standard AWS capability (no special permissions)

### Medium Risk
- Lambda logic changes are significant
- CIDR calculation bugs could cause conflicts or exhaustion
- Race conditions during parallel range creation

### Mitigation
- Comprehensive unit tests for CIDR calculation
- Deploy to dev first with extensive validation
- Monitor CloudWatch logs during initial rollout
- Rollback plan ready and tested
- Existing retry logic handles conflicts gracefully

## Files Modified

### Terraform (7 files)
1. `terraform/modules/range/vpc/main.tf` - Add secondary CIDRs, update SGs
2. `terraform/modules/range/vpc/outputs.tf` - Add all_cidr_blocks output
3. `terraform/modules/range/vpc/firewall.tf` - Update HOME_NET definitions
4. `terraform/modules/range/provisioner/variables.tf` - Change to list
5. `terraform/modules/range/provisioner/main.tf` - Update Lambda env vars
6. `terraform/environments/dev/portal/main.tf` - Pass list of prefixes
7. `terraform/environments/prod/portal/main.tf` - Pass list of prefixes

### Lambda (1 file)
8. `terraform/modules/range/provisioner/lambda/create_subnet/handler.py` - New logic

### Tests (1 new file)
9. `terraform/modules/range/provisioner/lambda/tests/test_create_subnet.py` - Unit tests

## Success Criteria
- [ ] Dev environment can create 300+ ranges
- [ ] New ranges get /28 subnets from all CIDR blocks
- [ ] Kali ↔ Victim connectivity works across all blocks
- [ ] Network Firewall rules apply correctly
- [ ] No errors in CloudWatch logs
- [ ] Existing ranges continue working
- [ ] Production deployment successful

## Documentation Updates
- Update `CLAUDE.md` with new capacity (16,384 ranges)
- Update `CHANGELOG.md` with VPC expansion feature
- Document secondary CIDR blocks and /28 subnet strategy
