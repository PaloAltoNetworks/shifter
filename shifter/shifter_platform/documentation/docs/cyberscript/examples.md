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
    os_type: kali        # Fixed Kali Linux AMI
    xdr_agent: false     # No agent on the attacker

  - name: Workstation
    role: victim
    os_type: from_agent  # OS determined by the user's uploaded agent
    xdr_agent: true      # Agent installed during provisioning

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
ngfw: true

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: Domain Controller
    role: dc                  # Domain controller role
    os_type: windows
    domain_controller: true   # Triggers AD provisioning
    xdr_agent: true
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Workstation
    role: victim
    os_type: from_agent
    xdr_agent: true
    join_domain: true         # Joins the internal.shifter domain

subnets:
  - name: core
    instances: [Attacker, Domain Controller, Workstation]
```

Key points:

- `domain_controller: true` + `dc_config` -- the Domain Controller instance sets up Active Directory with the `internal.shifter` domain
- `join_domain: true` on the Workstation -- after the DC is provisioned, the workstation joins the domain
- `role: dc` -- tells the Engine this is a domain controller, affecting provisioning order
- All instances in a single subnet despite `ngfw: true` -- the NGFW inspects traffic to/from the range but there is no inter-subnet segmentation

## Cortex BYOT (Bring Your Own Threat)

`cortex_byot.yaml` -- Full enterprise environment with multiple subnets.

```yaml
id: cortex_byot
name: Cortex BYOT
description: The classic Cortex XDR BYOT range with a ngfw, domain controller, two workstations, a server, and an attacker.
enabled: true
ngfw: true

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false
    join_domain: false

  - name: Domain Controller
    role: dc
    os_type: windows
    domain_controller: true
    xdr_agent: true
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Cortex Host
    role: victim
    os_type: ubuntu          # Fixed Ubuntu, not from_agent
    xdr_agent: true
    join_domain: true

  - name: Workstation 1
    role: victim
    os_type: windows         # Fixed Windows
    xdr_agent: true
    join_domain: true

  - name: Workstation 2
    role: victim
    os_type: windows
    xdr_agent: true
    join_domain: true

  - name: Server
    role: victim
    os_type: ubuntu
    xdr_agent: true
    join_domain: true

subnets:
  - name: dc_network
    instances: [Domain Controller, Cortex Host]
    connected_to: [workstation_network, server_network, attacker_network]

  - name: workstation_network
    instances: [Workstation 1, Workstation 2]
    connected_to: [dc_network, server_network, attacker_network]

  - name: server_network
    instances: [Server]
    connected_to: [dc_network, workstation_network, attacker_network]

  - name: attacker_network
    instances: [Attacker]
    connected_to: [dc_network, workstation_network, server_network]
```

Key points:

- Six instances across four subnets -- full enterprise topology
- Full mesh `connected_to` -- every subnet can reach every other subnet through the NGFW
- Mixed OS types -- Windows DCs and workstations, Ubuntu servers and Cortex host
- All victims have `xdr_agent: true` and `join_domain: true`
- Fixed OS types (no `from_agent`) -- this scenario requires both Windows and Linux agents

## Cortex Deployment Experience

`cortex_deployment_experience.yaml` -- Same topology as Cortex BYOT but with `xdr_agent: false` on all instances.

```yaml
id: cortex_deployment_experience
name: Cortex Deployment Experience
description: A range designed for use in the Cortex Deployment Experience. Includes a domain controller, two workstations, a server, and an attacker.
enabled: true
ngfw: true

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false
    join_domain: false

  - name: Domain Controller
    role: dc
    os_type: windows
    domain_controller: true
    xdr_agent: false         # No pre-installed agent
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Cortex Host
    role: victim
    os_type: ubuntu
    xdr_agent: false
    join_domain: true

  - name: Workstation 1
    role: victim
    os_type: windows
    xdr_agent: false
    join_domain: true

  - name: Workstation 2
    role: victim
    os_type: windows
    xdr_agent: false
    join_domain: true

  - name: Server
    role: victim
    os_type: ubuntu
    xdr_agent: false
    join_domain: true

subnets:
  - name: dc_network
    instances: [Domain Controller, Cortex Host]
    connected_to: [workstation_network, server_network, attacker_network]

  - name: workstation_network
    instances: [Workstation 1, Workstation 2]
    connected_to: [dc_network, server_network, attacker_network]

  - name: server_network
    instances: [Server]
    connected_to: [dc_network, workstation_network, attacker_network]

  - name: attacker_network
    instances: [Attacker]
    connected_to: [dc_network, workstation_network, server_network]
```

Key points:

- Identical topology to Cortex BYOT
- `xdr_agent: false` everywhere -- the user deploys agents manually as part of the Cortex Deployment Experience exercise
- Does not require agent upload at launch time since `requires_agent()` returns `false`
