# NGFW Configuration Commands

Working PAN-OS CLI commands for configuring the NGFW data plane.

## Context

- NGFW Management IP: 10.1.4.247
- NGFW Data ENI IP: 10.1.4.4
- NGFW Subnet: 10.1.4.0/22
- VPC Gateway (next-hop): 10.1.4.1

---

# NGFW Provisioning (one-time setup)

## 1. Configure ethernet1/1 as Layer 3 with DHCP + Virtual Router

```
configure
set network virtual-router default interface ethernet1/1
set network interface ethernet ethernet1/1 layer3 dhcp-client create-default-route no
commit
```

**Result:** ethernet1/1 gets IP from AWS DHCP, assigned to virtual router `default`.

---

## 2. Create shared zone and assign ethernet1/1 to it

```
configure
set zone ranges network layer3 ethernet1/1
commit
```

**Result:** Creates zone `ranges` and assigns ethernet1/1 to it. All range traffic will use this shared zone.

---

## 3. Delete the allow-all rule (if it exists)

```
configure
delete rulebase security rules allow-all
commit
```

**Result:** Removes the default allow-all rule so traffic hits per-range rules with logging enabled.
**Note:** This rule bypasses per-range logging if left in place.

---

# Range Creation (per-range setup)

## 4. Add static routes for range subnets

```
configure
set network virtual-router default routing-table ip static-route range-{range_id}-attack destination {attack_subnet_cidr} interface ethernet1/1 nexthop ip-address {vpc_gateway_ip}
set network virtual-router default routing-table ip static-route range-{range_id}-target destination {target_subnet_cidr} interface ethernet1/1 nexthop ip-address {vpc_gateway_ip}
commit
```

**Example for Range 97:**
```
configure
set network virtual-router default routing-table ip static-route range-97-attack destination 10.1.2.0/28 interface ethernet1/1 nexthop ip-address 10.1.4.1
set network virtual-router default routing-table ip static-route range-97-target destination 10.1.2.16/28 interface ethernet1/1 nexthop ip-address 10.1.4.1
commit
```

**Result:** Static routes added for both range subnets via ethernet1/1 with next-hop pointing to VPC gateway.
**Note:** Next-hop must be the VPC gateway IP (first IP of the NGFW subnet).

---

## 5. Create security policy with logging

```
configure
set rulebase security rules range-{range_id}-allow from ranges to ranges source {attack_subnet_cidr} destination {target_subnet_cidr} application any service any action allow
set rulebase security rules range-{range_id}-allow source {target_subnet_cidr} destination {attack_subnet_cidr}
set rulebase security rules range-{range_id}-allow log-setting XDR-Forward
set rulebase security rules range-{range_id}-allow log-end yes
commit
```

**Example for Range 97:**
```
configure
set rulebase security rules range-97-allow from ranges to ranges source any destination any application any service any action allow
set rulebase security rules range-97-allow log-setting XDR-Forward
set rulebase security rules range-97-allow log-end yes
commit
```

**Result:** Security rule allows bidirectional traffic between range subnets, with logging to XDR/Cortex Data Lake.
**Note:**
- `log-setting XDR-Forward` attaches the existing log forwarding profile
- `log-end yes` enables logging at session end

---

# Range Teardown (per-range cleanup)

## 6. Remove range configuration

```
configure
delete network virtual-router default routing-table ip static-route range-{range_id}-attack
delete network virtual-router default routing-table ip static-route range-{range_id}-target
delete rulebase security rules range-{range_id}-allow
commit
```

**Result:** Removes routes and security rule for the range.
