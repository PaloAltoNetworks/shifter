# Shared Constants — Cross-Asset Values

These values must be consistent across multiple assets. This file is the single source of truth.

## Controller Identity (A10, A11, A12)

Used by: A10, A11, A12 (device ID responses), A13 (handshake key derivation), A9 (flag 31 answer)

| Controller | Vendor | Model | Serial |
|-----------|--------|-------|--------|
| A10 Tail | AURORA HEAVY SYSTEMS | AHS-TAIL-7741 | AHS-T-00482 |
| A11 Leg | AURORA HEAVY SYSTEMS | AHS-LEG-MN07 | AHS-L-00483 |
| A12 Arms | AURORA HEAVY SYSTEMS | AHS-ARM-AL42 | AHS-A-00484 |

### Flag 31 — OT network enumeration

Flag 31 answer is the concatenation of the three model numbers in network order (A10, A11, A12):

```
AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42
```

Submitted to CTFd as: `FLAG{2e8c0a5d7f3b1946}` (static flag, not derived)

### A13 Handshake Key

```python
import hashlib
serials = "AHS-T-00482" + "AHS-L-00483" + "AHS-A-00484"
key = hashlib.sha256(serials.encode()).digest()[:8]
# key = first 8 bytes of SHA256("AHS-T-00482AHS-L-00483AHS-A-00484")
```

## Override Code (A13 flag 36)

The override code `7741-MN07-AL42` is assembled from three pieces found across the range:

| Piece | Value | Source Asset | Location |
|-------|-------|-------------|----------|
| First 4 chars | `7741` | A0 | Boreas Systems registration number on About Us page (near flag 1 area) |
| Middle 4 chars | `MN07` | A6 | MIDNIGHT-7 simulation ID in `MIDNIGHT-7_results.dat` (`MN07-INTEG-20251028`, take `MN07`) |
| Last 4 chars | `AL42` | A8 | Assembly log metadata in `compartment_c.assembly_log` final row JSONB (`integration_code: "AL42"`) |

Full code: `7741-MN07-AL42`

## BRAIN_AUTH_TOKEN (A13 authentication)

```
a4f8e2c1d7b03965e8f2a1c4d7b03965
```

Source: A7 `aurora/navigation-controller/config.yaml` → `brain_connection.auth_token`
Used by: A13 authentication (password for user `vasik`)

## GPG Passphrase (A6 flag 30 chain)

```
Pr0m3th3us_Unb0und_2024
```

Source: A7 `aurora/weapons-integration/src/crypto_config.py` → `LEGACY_PASSPHRASE`
Used by: Decrypting A6 `/tmp/.deleted/full_integration_sim.mp4.gpg` after importing private key from A8

## Service Account Credentials (cross-asset)

| Account | Password | Source | Used At |
|---------|----------|-------|---------|
| svc-backup | `Password1` | A2 (Kerberoast) | A2 DCSync for flag 17 |
| svc-scada | `Sc@da#2025!` | A2 (Kerberoast) or A4 IT share | A5 HMI control panel auth |
| d.kowalski | `P@ssw0rd123` | A0 employee info + guessing, or A3 config | A1 webmail (flag 10), creds in sent mail → A4 (flag 15) |

## PO Number (A12 cross-zone intel)

```
2847
```

Source: A4 `Procurement/PO-2847_hydraulic_actuators.pdf`
Used by: A12 arms controller flag 34 (XOR key for rolling nonce challenge)
