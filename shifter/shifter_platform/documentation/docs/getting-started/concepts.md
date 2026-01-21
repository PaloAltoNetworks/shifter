# Key Concepts

## Agent

Your XDR or XSIAM installer. Download it from your console, upload it to Shifter. Gets deployed to victim machines when you launch a range.

## Range

An isolated demo environment. Contains attacker machine(s) and victim machine(s) in a private network. Each range is independent - your attacks don't affect other users.

## Scenario

A template that defines what a range contains. Different scenarios for different demo needs:

| Scenario | What It Includes | Use Case |
|----------|------------------|----------|
| Basic Range | Kali + 1 victim | Quick demos, simple attacks |
| AD Attack Lab | Kali + DC + domain victim | Active Directory attacks |
| Basic Range with NGFW | Basic Range + firewall | Traffic logging to XDR/XSIAM |
| Cortex BYOT | Full enterprise setup | Complex multi-machine scenarios |

## Terminal

Browser-based access to your range instances. SSH for command line, RDP for graphical access (Windows, Kali desktop).

## Credentials

Authentication info for integrations:

- **SCM Credentials** - For Strata Cloud Manager device association
- **Deployment Profiles** - For software NGFW deployment

Only needed for NGFW scenarios.

## NGFW

Next-Generation Firewall. A persistent firewall instance that logs traffic to your XDR/XSIAM. Set it up once, reuse across range launches.
