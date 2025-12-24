---
name: portal-admin
description: Access the Django admin panel via SSM tunnel. Use when the user needs to access Django admin, manage users, view admin data, or troubleshoot the portal application directly.
---

# Portal Admin Access

Access the Django admin panel on dev or prod via SSM port forwarding.

## Start the Tunnel

```bash
./scripts/portal-admin-tunnel.sh           # Dev (default)
./scripts/portal-admin-tunnel.sh -e prod   # Prod
```

This opens a tunnel to the portal EC2 instance:
- **Local URL**: http://localhost:9000/admin/
- **Remote Port**: 8000 (Django dev server on EC2)

## Access Admin

Once the tunnel is running, access:
- http://localhost:9000/admin/

## Notes

- The portal EC2 may be stopped (scheduled off 10pm-6am PST to save costs)
- Uses AWS SSM Session Manager (no SSH keys required)
- Requires appropriate AWS profile set via `PANW_SHIFTER_DEV_PROFILE` or `PANW_SHIFTER_PROD_PROFILE`
