# Scenarios

A scenario defines what your range contains. Choose based on your demo needs.

## Available Scenarios

| Scenario | Instances | NGFW | Best For |
|----------|-----------|------|----------|
| [Basic Range](basic-range) | Kali, Workstation | No | Quick demos, simple attacks |
| [AD Attack Lab](ad-attack-lab) | Kali, DC, Workstation | No | Active Directory attacks |
| [Basic Range with NGFW](ngfw-range) | Kali, Workstation | Yes | Traffic logging demos |
| AD Attack Lab with NGFW | Kali, DC, Workstation | Yes | AD attacks with network visibility + Cortex XDR |

## GCP VM range-cell support

This table is an operator evidence projection, not a runtime allowlist. The
canonical scenario hydrator and the GCE compatibility realizer decide whether a
specific, digest-bound composition is realizable. The realizer fails before
provider mutation when the composition needs a capability the GCE cell does not
provide.

| Scenario/composition | GCP status | Current evidence or required action |
|---|---|---|
| `basic` | Supported by contract | Agent hydration must resolve to a configured Linux or Windows image profile. Unit/contract coverage was refreshed 2026-07-27; the Linux smoke below is the required live environment evidence. |
| `smoke_linux`, `smoke_windows` (operator-only) | Supported validation paths | Create through CMS, reach READY, probe the Kali guest over SSH or plain Windows guest over RDP, then destroy by request ownership. The Linux variant supplies the required non-Polaris evidence. |
| `polaris` | Supported with prerequisites | Requires exact `polaris-vm` and `polaris-dc` profiles declaring the Polaris-host and matching `boreas.local` pre-promoted-domain capabilities, plus the bootstrap inputs documented in the GCP deploy runbook. |
| `ad_attack_lab` | Prerequisite-blocked | Its domain controller requires a pre-promoted profile whose configured DNS and NetBIOS identity exactly match the authored `internal.shifter` domain. Add and configure that image contract before enabling this composition on GCP. |
| `basic_ngfw`, `ad_attack_lab_ngfw` | Unsupported capability | GCE range cells do not implement the NGFW attachment and segmented-routing contract. The request fails with `unsupported-capability`; it never falls back to GDC or pods. |

Other legacy or CTF scenarios follow the same capability rules: no NGFW,
domain-intent DCs require exact pre-promoted domain metadata, every image key
must resolve exactly, and each configured bootstrap capability must have a GCP
implementation. AWS behavior is unchanged.

## Quick Comparison

**No NGFW required:**
- [Basic Range](basic-range) - Fastest, simplest
- [AD Attack Lab](ad-attack-lab) - AD attacks without network logging

**NGFW required:**
- [Basic Range with NGFW](ngfw-range) - Simple + network visibility
- AD Attack Lab with NGFW - AD topology + NGFW segmentation + Cortex XDR

## Provisioning Time

| Scenario | Typical Time |
|----------|--------------|
| Basic Range | 2-5 minutes |
| AD Attack Lab | 5-10 minutes |
| Basic Range with NGFW | 3-7 minutes |
| AD Attack Lab with NGFW | 6-12 minutes |

Times vary based on infrastructure load.
