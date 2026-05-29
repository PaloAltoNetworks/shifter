# Examples

Annotated examples from the built-in scenario templates in `cms/scenarios/templates/`.

## Basic Range

`basic.yaml` -- Simplest attacker-victim scenario.

```yaml
id: basic
name: Basic Range
description: A basic attacker-victim range with Kali Linux attacker and user-provided agent on victim.
enabled: true
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali        # Fixed Kali Linux image
    xdr_agent: false     # No agent on the attacker

  - name: Workstation
    role: victim
    os_type: from_agent  # OS determined by the user's uploaded agent
    xdr_agent: false     # No Cortex XDR agent — bring your own EDR/agent

subnets:
  - name: core
    instances: [Attacker, Workstation]  # Both in the same subnet, free communication
```

Key points:

- `ngfw: false` -- no firewall, flat network
- `from_agent` on the victim -- the user selects a Windows or Linux agent at launch time, and the victim OS matches
- Single subnet -- attacker and victim can communicate directly

## Basic Range with NGFW

`basic_ngfw.yaml` -- Same as basic, but traffic routed through an NGFW.

```yaml
id: basic_ngfw
name: Basic Range with NGFW
description: A basic attacker-victim range with Kali Linux attacker and user-provided agent on victim.
enabled: true
ngfw: true

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: Workstation
    role: victim
    os_type: from_agent
    xdr_agent: true

subnets:
  - name: attack
    instances: [Attacker]
    connected_to: [target]   # Attacker can reach the target subnet

  - name: target
    instances: [Workstation]
    connected_to: [attack]   # Workstation can reach the attack subnet
```

Key points:

- `ngfw: true` -- NGFW provisioned alongside instances
- Two subnets with bidirectional `connected_to` -- traffic between attacker and workstation routes through the NGFW
- Each subnet has exactly one instance -- standard segmentation pattern

## AD Attack Lab

`ad_attack_lab.yaml` -- Active Directory environment with domain controller.

```yaml
id: ad_attack_lab
name: AD Attack Lab
description: Active Directory attack lab with domain controller, Kali attacker, and domain-joined Windows victim.
enabled: true
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: Domain Controller
    role: dc                  # Domain controller role
    os_type: windows
    domain_controller: true   # Triggers AD provisioning
    xdr_agent: false
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Workstation
    role: victim
    os_type: from_agent
    xdr_agent: false
    join_domain: true         # Joins the internal.shifter domain

subnets:
  - name: core
    instances: [Attacker, Domain Controller, Workstation]
```

Key points:

- `domain_controller: true` + `dc_config` -- the Domain Controller instance sets up Active Directory with the `internal.shifter` domain
- `join_domain: true` on the Workstation -- after the DC is provisioned, the workstation joins the domain
- `role: dc` -- tells the Engine this is a domain controller, affecting provisioning order
- `ngfw: false` and `xdr_agent: false` everywhere -- pure AD without Palo Alto-specific tooling

## AD Attack Lab with NGFW

`ad_attack_lab_ngfw.yaml` -- Same topology as the AD Attack Lab, with NGFW segmentation and Cortex XDR on the Windows instances.

```yaml
id: ad_attack_lab_ngfw
name: AD Attack Lab with NGFW
description: Active Directory attack lab with NGFW segmentation, domain controller, Kali attacker, and domain-joined Windows victim. Cortex XDR agent on Windows instances.
enabled: true
ngfw: true

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: Domain Controller
    role: dc
    os_type: windows
    domain_controller: true
    xdr_agent: true
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Workstation
    role: victim
    os_type: from_agent
    xdr_agent: true
    join_domain: true

subnets:
  - name: attack
    instances: [Attacker]
    connected_to: [target]

  - name: target
    instances: [Domain Controller, Workstation]
    connected_to: [attack]
```

Key points:

- Same AD topology as `ad_attack_lab` plus NGFW-routed attack/target segmentation
- `xdr_agent: true` on the Windows DC and Workstation -- end-to-end Cortex XDR + NGFW traffic visibility

## (Removed)

Earlier releases shipped two additional Cortex-specific templates (`cortex_byot` and `cortex_deployment_experience`). They have been removed; use `ad_attack_lab_ngfw` for a Windows AD + NGFW topology with Cortex XDR.
