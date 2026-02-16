#!/usr/bin/env python3
"""
Find EC2 instances that are still running/stopped but belong to destroyed or failed ranges.

Inputs (one instance ID per line, e.g. i-0abc123):
  - current_ec2.txt: instance IDs from AWS (running + stopped, exclude terminated)
  - destroyed_failed_from_db.txt: instance IDs from DB for ranges with status destroyed/failed

Output: instance IDs that appear in BOTH files (orphans), one per line, plus a summary.

Usage:
  # 1. Export current EC2 instance IDs (prod, non-terminated, shifter range instances only)
  #    e.g. from MCP list_ec2_instances or:
  #    aws ec2 describe-instances --profile panw-shifter-prod-workstation --region us-east-2 \
  #      --filters "Name=instance-state-name,Values=running,stopped" \
  #      --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0]]' --output text \
  #      | awk '{print $1}' > current_ec2.txt

  # 2. Export destroyed/failed instance IDs from DB (prod). SQL (output instance_id column to file):

  WITH bad_ranges AS (
    SELECT id, victim_instance_id, kali_instance_id, provisioned_instances
    FROM mission_control_range WHERE status IN ('destroyed', 'failed')
  ),
  from_columns AS (
    SELECT unnest(ARRAY[victim_instance_id, kali_instance_id]) AS instance_id FROM bad_ranges
    WHERE (victim_instance_id IS NOT NULL AND victim_instance_id != '')
       OR (kali_instance_id IS NOT NULL AND kali_instance_id != '')
  ),
  from_json AS (
    SELECT elem->>'instance_id' AS instance_id FROM bad_ranges r,
    jsonb_array_elements(COALESCE(r.provisioned_instances, '[]'::jsonb)) elem
    WHERE elem->>'instance_id' IS NOT NULL AND elem->>'instance_id' != ''
  )
  SELECT instance_id FROM from_columns WHERE instance_id != ''
  UNION SELECT instance_id FROM from_json;

  python3 scripts/find-orphan-instances.py current_ec2.txt destroyed_failed_from_db.txt
"""
import sys


def load_ids(path: str) -> set[str]:
    out = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and line.startswith("i-"):
                out.add(line)
    return out


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: find-orphan-instances.py <current_ec2.txt> <destroyed_failed_from_db.txt>",
            file=sys.stderr,
        )
        sys.exit(2)
    current_path = sys.argv[1]
    destroyed_failed_path = sys.argv[2]

    current = load_ids(current_path)
    destroyed_failed = load_ids(destroyed_failed_path)

    orphans = current & destroyed_failed
    orphans_sorted = sorted(orphans)

    for iid in orphans_sorted:
        print(iid)

    print(
        f"\n# Summary: {len(orphans_sorted)} orphan instance(s) (in AWS but range is destroyed/failed). "
        f"Current EC2 total: {len(current)}, Destroyed/failed from DB: {len(destroyed_failed)}.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
