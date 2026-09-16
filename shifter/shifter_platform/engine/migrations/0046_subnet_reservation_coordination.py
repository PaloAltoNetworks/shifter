# Move synchronous subnet reservation behind an Engine-owned coordination
# surface and revoke the provisioner's allocation-table capability
# (ADR-043-R6, #1838, phase 6 of #478).
#
# Reservation is pre-mutation coordination: the CIDRs must be decided and durably
# reserved *before* Terraform creates anything, under the PostgreSQL serialization
# that has always guarded them. It therefore cannot ride the asynchronous
# operation-result inbox, and the separately deployed provisioner cannot run Engine
# Python. ADR-043-R1 reserves exactly one narrow exception for this case -- "an
# explicitly reviewed stable coordination surface for synchronous reservations" --
# and these three routines are it.
#
# The routines are the whole API. The provisioner receives EXECUTE on them and
# nothing else: after this migration its role has no SELECT/INSERT/UPDATE/DELETE on
# engine_subnetallocation and no rights on its sequence. PostgreSQL grants are part
# of the contract, so the surface is deliberately tiny -- reserve, read, release --
# with no caller-selected table, column, predicate, or range id anywhere in it.
#
# Hardening, because SECURITY DEFINER runs as the definer and every argument is
# untrusted input to a privileged context:
#   - fixed `search_path = pg_catalog, pg_temp` and fully-qualified public.* objects,
#     so no schema on the caller's path can shadow a table or operator;
#   - no dynamic SQL anywhere, so no argument can become an identifier;
#   - owned by the migration role (never provisioner_lambda), so the callee cannot
#     be redefined by the caller;
#   - REVOKE ALL FROM PUBLIC before the narrow GRANT, since functions are
#     world-executable by default.
#
# Migrations 0018/0019 granted the capability being removed here. They are history,
# not edit targets (ADR-043: forward migrations only).

from django.db import migrations, models

_ROLE = "provisioner_lambda"

# The routine bodies below are written as plain literals rather than interpolated
# from Python constants. Interpolation would buy nothing -- every value is fixed at
# authoring time -- while building a `SELECT ... FROM ...` shape out of string
# pieces, which is both what B608 exists to catch and a pattern a later edit could
# turn into a real injection. Migration 0045 documents the same choice.
#
# The custom SQLSTATEs the routines raise, and the fixed reason code each maps to
# (the mapping itself lives in `shared.subnet_coordination._REASON_BY_SQLSTATE`):
#   SH001 subnet_reservation_conflict   SH004 unknown_operation
#   SH002 subnet_pool_exhausted         SH005 invalid_reservation_request
#   SH003 stale_operation_generation    SH006 operation_not_permitted
#
# Candidate generation reserves the first two /24 blocks (512 addresses) for
# infrastructure and excludes the final /24 (256 addresses) -- the allocation
# policy that has always applied, previously expressed as "third octet 2..254" in
# the provisioner's candidate generators, which these routines replace as the
# single implementation.

_RESERVE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.engine_reserve_subnet_cidrs(
    p_contract_version text,
    p_operation_id uuid,
    p_request_id uuid,
    p_network_id text,
    p_network_cidr cidr,
    p_prefix_length integer,
    p_subnet_count integer,
    p_observed_cidrs cidr[],
    p_shape_fingerprint text
)
RETURNS TABLE (ordinal integer, subnet_cidr text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_range_id integer;
    v_generation uuid;
    v_existing_count integer;
    v_existing_shapes text[];
    v_operation text;
    v_picked inet[];
    v_total bigint;
    v_block bigint;
    v_first bigint;
    v_last bigint;
BEGIN
    IF p_contract_version IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'unsupported coordination contract version'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_operation_id IS NULL OR p_request_id IS NULL THEN
        RAISE EXCEPTION 'operation and request identity are required'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_network_id IS NULL OR p_network_id = '' OR p_network_cidr IS NULL THEN
        RAISE EXCEPTION 'network identity is required'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_prefix_length IS NULL OR p_prefix_length NOT IN (24, 28) THEN
        RAISE EXCEPTION 'unsupported prefix length'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_subnet_count IS NULL OR p_subnet_count < 1 OR p_subnet_count > 64 THEN
        RAISE EXCEPTION 'subnet count out of bounds'
            USING ERRCODE = 'SH005';
    END IF;
    IF pg_catalog.family(p_network_cidr) <> 4 OR p_prefix_length < pg_catalog.masklen(p_network_cidr) THEN
        RAISE EXCEPTION 'prefix length is not carvable from the network'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_observed_cidrs IS NOT NULL AND pg_catalog.array_length(p_observed_cidrs, 1) > 4096 THEN
        RAISE EXCEPTION 'too many observed networks'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_shape_fingerprint IS NULL OR p_shape_fingerprint = '' THEN
        RAISE EXCEPTION 'reservation shape fingerprint is required'
            USING ERRCODE = 'SH005';
    END IF;

    -- Ownership is resolved here, from persisted Engine state. The caller names
    -- a request and a generation; it never names the range row it wants.
    SELECT r.id, r.provisioner_operation_id
      INTO v_range_id, v_generation
      FROM public.mission_control_range r
      JOIN public.engine_request q ON q.id = r.request_id
     WHERE q.request_id = p_request_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range is bound to this request'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_generation IS NULL OR v_generation <> p_operation_id THEN
        RAISE EXCEPTION 'operation generation is not current for this range'
            USING ERRCODE = 'SH003';
    END IF;

    -- A current generation is necessary but not sufficient: it says *an*
    -- operation is in flight for this range, not that it is one this verb may
    -- serve. Resolve what the Engine actually authorized and bind the verb to it,
    -- so a destroy generation cannot reserve and a provision generation cannot
    -- release live reservations.
    SELECT i.operation
      INTO v_operation
      FROM public.engine_operation_input i
     WHERE i.operation_id = p_operation_id
       AND i.request_id = p_request_id
       AND i.resource = 'range';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range operation input is materialized for this generation'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_operation <> 'provision' THEN
        RAISE EXCEPTION 'this operation may not reserve subnets'
            USING ERRCODE = 'SH006';
    END IF;

    -- Serializes every concurrent allocation, including against an empty table,
    -- and is held until the caller's transaction commits. Nothing below may be
    -- reordered before it.
    LOCK TABLE public.engine_subnetallocation IN EXCLUSIVE MODE;

    -- Ownership-idempotent retry: the same generation asking for the same shape
    -- gets its existing batch back rather than leaking a second one.
    --
    -- Scoped to the request across *every* network, not to the requested one: a
    -- retry that arrives with a different network would otherwise find nothing,
    -- reserve a second batch, and strand the first with no owner able to release
    -- it. A changed network is a conflict, not permission to allocate again.
    SELECT pg_catalog.count(*)::integer,
           pg_catalog.array_agg(DISTINCT a.reservation_shape)
      INTO v_existing_count, v_existing_shapes
      FROM public.engine_subnetallocation a
     WHERE a.request_id = p_request_id::text
       AND a.range_id <> 0;

    IF v_existing_count > 0 THEN
        -- One comparison covers network, base CIDR, prefix length, and the
        -- ordered authored subnet identities: the fingerprint is computed over
        -- all of them, so a retry that would realize anything different fails
        -- here instead of receiving the first batch zipped onto a new order.
        IF v_existing_count <> p_subnet_count
           OR v_existing_shapes IS DISTINCT FROM ARRAY[p_shape_fingerprint] THEN
            RAISE EXCEPTION 'an existing reservation for this request has a different shape'
                USING ERRCODE = 'SH001';
        END IF;
        RETURN QUERY
            SELECT (pg_catalog.row_number() OVER (ORDER BY a.id))::integer, a.cidr::text
              FROM public.engine_subnetallocation a
             WHERE a.request_id = p_request_id::text
               AND a.range_id <> 0
             ORDER BY a.id;
        RETURN;
    END IF;

    -- Drift repair: provider-observed networks the table does not know about
    -- become unowned occupancy evidence before any candidate is chosen.
    IF p_observed_cidrs IS NOT NULL THEN
        INSERT INTO public.engine_subnetallocation
            (vpc_id, cidr, subnet_size, range_id, request_id, reservation_shape, created_at)
        SELECT p_network_id,
               pg_catalog.text(o),
               pg_catalog.masklen(o),
               0,
               '',
               '',
               pg_catalog.now()
          FROM pg_catalog.unnest(p_observed_cidrs) AS o
        ON CONFLICT (vpc_id, cidr) DO NOTHING;
    END IF;

    v_total := (2::bigint) ^ (32 - pg_catalog.masklen(p_network_cidr));
    v_block := (2::bigint) ^ (32 - p_prefix_length);
    v_first := 512;
    v_last := v_total - 256;

    IF v_last <= v_first THEN
        RAISE EXCEPTION 'network is too small to carve allocatable subnets from'
            USING ERRCODE = 'SH002';
    END IF;

    -- Candidate order is ascending network address, matching the deterministic
    -- order the provisioner's generators produced. Occupancy is tested by inet
    -- overlap, so a wider tracked or observed network masks every candidate
    -- inside it -- string equality would not.
    -- The LIMIT has to bound the candidate rows, so it lives in its own
    -- subquery: applied alongside the aggregate it would bound the single
    -- aggregated row instead and quietly reserve the whole free pool.
    SELECT pg_catalog.array_agg(picked.candidate ORDER BY picked.candidate)
      INTO v_picked
      FROM (
        SELECT c.candidate
          FROM (
            SELECT pg_catalog.set_masklen(
                       pg_catalog.network(p_network_cidr) + g, p_prefix_length
                   ) AS candidate
              FROM pg_catalog.generate_series(v_first, v_last - v_block, v_block) AS g
          ) c
         WHERE NOT EXISTS (
            SELECT 1
              FROM public.engine_subnetallocation a
             WHERE a.vpc_id = p_network_id
               AND a.cidr::inet && c.candidate
         )
         ORDER BY c.candidate
         LIMIT p_subnet_count
      ) picked;

    IF v_picked IS NULL OR pg_catalog.array_length(v_picked, 1) <> p_subnet_count THEN
        RAISE EXCEPTION 'not enough free subnets remain in this network'
            USING ERRCODE = 'SH002';
    END IF;

    INSERT INTO public.engine_subnetallocation
        (vpc_id, cidr, subnet_size, range_id, request_id, reservation_shape, created_at)
    SELECT p_network_id,
           pg_catalog.text(v_picked[i]),
           p_prefix_length,
           v_range_id,
           p_request_id::text,
           p_shape_fingerprint,
           pg_catalog.now()
      FROM pg_catalog.generate_subscripts(v_picked, 1) AS i
     ORDER BY i;

    RETURN QUERY
        SELECT i::integer, pg_catalog.text(v_picked[i])
          FROM pg_catalog.generate_subscripts(v_picked, 1) AS i
         ORDER BY i;
END;
$$;
"""

_READ_FUNCTION = """
CREATE OR REPLACE FUNCTION public.engine_read_subnet_reservation(
    p_contract_version text,
    p_operation_id uuid,
    p_request_id uuid
)
RETURNS TABLE (ordinal integer, subnet_cidr text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_generation uuid;
    v_operation text;
BEGIN
    IF p_contract_version IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'unsupported coordination contract version'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_operation_id IS NULL OR p_request_id IS NULL THEN
        RAISE EXCEPTION 'operation and request identity are required'
            USING ERRCODE = 'SH005';
    END IF;

    SELECT r.provisioner_operation_id
      INTO v_generation
      FROM public.mission_control_range r
      JOIN public.engine_request q ON q.id = r.request_id
     WHERE q.request_id = p_request_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range is bound to this request'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_generation IS NULL OR v_generation <> p_operation_id THEN
        RAISE EXCEPTION 'operation generation is not current for this range'
            USING ERRCODE = 'SH003';
    END IF;

    -- Bind the verb to the operation the Engine actually authorized, not merely
    -- to a current generation. Provision reads its own reservation on retry;
    -- destroy reads it to tear the range down. Both may read.
    SELECT i.operation
      INTO v_operation
      FROM public.engine_operation_input i
     WHERE i.operation_id = p_operation_id
       AND i.request_id = p_request_id
       AND i.resource = 'range';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range operation input is materialized for this generation'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_operation NOT IN ('provision', 'destroy') THEN
        RAISE EXCEPTION 'this operation may not read subnet reservations'
            USING ERRCODE = 'SH006';
    END IF;

    RETURN QUERY
        SELECT (pg_catalog.row_number() OVER (ORDER BY a.id))::integer, a.cidr::text
          FROM public.engine_subnetallocation a
         WHERE a.request_id = p_request_id::text
           AND a.range_id <> 0
         ORDER BY a.id;
END;
$$;
"""

_RELEASE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.engine_release_subnet_reservation(
    p_contract_version text,
    p_operation_id uuid,
    p_request_id uuid
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_generation uuid;
    v_operation text;
    v_released integer;
BEGIN
    IF p_contract_version IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'unsupported coordination contract version'
            USING ERRCODE = 'SH005';
    END IF;
    IF p_operation_id IS NULL OR p_request_id IS NULL THEN
        RAISE EXCEPTION 'operation and request identity are required'
            USING ERRCODE = 'SH005';
    END IF;

    SELECT r.provisioner_operation_id
      INTO v_generation
      FROM public.mission_control_range r
      JOIN public.engine_request q ON q.id = r.request_id
     WHERE q.request_id = p_request_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range is bound to this request'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_generation IS NULL OR v_generation <> p_operation_id THEN
        RAISE EXCEPTION 'operation generation is not current for this range'
            USING ERRCODE = 'SH003';
    END IF;

    -- Bind the verb to the operation the Engine actually authorized, not merely
    -- to a current generation. Release belongs to failed-provision compensation
    -- and to successful destroy; a pause or resume generation holding a current
    -- id must not be able to hand a live range's CIDRs back to the pool.
    SELECT i.operation
      INTO v_operation
      FROM public.engine_operation_input i
     WHERE i.operation_id = p_operation_id
       AND i.request_id = p_request_id
       AND i.resource = 'range';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no range operation input is materialized for this generation'
            USING ERRCODE = 'SH004';
    END IF;
    IF v_operation NOT IN ('provision', 'destroy') THEN
        RAISE EXCEPTION 'this operation may not release subnet reservations'
            USING ERRCODE = 'SH006';
    END IF;

    -- range_id <> 0 keeps drift-observed occupancy out of reach: it is evidence
    -- about the provider, not something this range reserved and may hand back.
    DELETE FROM public.engine_subnetallocation a
     WHERE a.request_id = p_request_id::text
       AND a.range_id <> 0;

    GET DIAGNOSTICS v_released = ROW_COUNT;
    RETURN v_released;
END;
$$;
"""

_DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS public.engine_release_subnet_reservation(text, uuid, uuid);
DROP FUNCTION IF EXISTS public.engine_read_subnet_reservation(text, uuid, uuid);
DROP FUNCTION IF EXISTS public.engine_reserve_subnet_cidrs(
    text, uuid, uuid, text, cidr, integer, integer, cidr[], text);
"""

# Functions are executable by PUBLIC by default, so the REVOKE is what makes the
# GRANT meaningful.
_HARDEN_AND_GRANT = """
REVOKE ALL ON FUNCTION public.engine_reserve_subnet_cidrs(
    text, uuid, uuid, text, cidr, integer, integer, cidr[], text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.engine_read_subnet_reservation(text, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.engine_release_subnet_reservation(text, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.engine_reserve_subnet_cidrs(
    text, uuid, uuid, text, cidr, integer, integer, cidr[], text) TO provisioner_lambda;
GRANT EXECUTE ON FUNCTION public.engine_read_subnet_reservation(text, uuid, uuid) TO provisioner_lambda;
GRANT EXECUTE ON FUNCTION public.engine_release_subnet_reservation(text, uuid, uuid) TO provisioner_lambda;
"""

# The capability the coordination surface replaces. Written as literals: the table,
# sequence and role are fixed at authoring time, and DDL cannot bind identifiers as
# parameters, so a literal is the construction with no dynamic input at all.
_REVOKE_TABLE_ACCESS = """
REVOKE SELECT, INSERT, UPDATE, DELETE ON engine_subnetallocation FROM provisioner_lambda;
REVOKE USAGE, SELECT ON SEQUENCE engine_subnetallocation_id_seq FROM provisioner_lambda;
"""

_RESTORE_TABLE_ACCESS = """
GRANT SELECT, INSERT, UPDATE, DELETE ON engine_subnetallocation TO provisioner_lambda;
GRANT USAGE, SELECT ON SEQUENCE engine_subnetallocation_id_seq TO provisioner_lambda;
"""


def _role_exists(schema_editor) -> bool:
    """Return True when the database role exists (absent in some local setups)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [_ROLE])
        return cursor.fetchone() is not None


def _is_postgres(schema_editor) -> bool:
    """Return True on PostgreSQL, where these routines and grants are meaningful."""
    return schema_editor.connection.vendor == "postgresql"


def create_coordination_surface(apps, schema_editor):
    """Create the coordination routines, then revoke the direct table capability."""
    if not _is_postgres(schema_editor):
        return
    schema_editor.execute(_RESERVE_FUNCTION)
    schema_editor.execute(_READ_FUNCTION)
    schema_editor.execute(_RELEASE_FUNCTION)
    if _role_exists(schema_editor):
        schema_editor.execute(_HARDEN_AND_GRANT)
        schema_editor.execute(_REVOKE_TABLE_ACCESS)
    else:
        # No role to grant to, but PUBLIC must still lose the default EXECUTE.
        schema_editor.execute(
            "\n".join(line for line in _HARDEN_AND_GRANT.splitlines() if not line.strip().startswith("GRANT"))
        )


def drop_coordination_surface(apps, schema_editor):
    """Restore the direct table capability and drop the routines."""
    if not _is_postgres(schema_editor):
        return
    if _role_exists(schema_editor):
        schema_editor.execute(_RESTORE_TABLE_ACCESS)
    schema_editor.execute(_DROP_FUNCTIONS)


class Migration(migrations.Migration):
    """Publish the subnet coordination routines and revoke direct table access."""

    dependencies = [
        ("engine", "0045_revoke_aces_reads_from_provisioner"),
    ]

    operations = [
        migrations.AddField(
            model_name="subnetallocation",
            name="reservation_shape",
            field=models.CharField(blank=True, default="", max_length=71),
        ),
        migrations.RunPython(create_coordination_surface, drop_coordination_surface),
    ]
