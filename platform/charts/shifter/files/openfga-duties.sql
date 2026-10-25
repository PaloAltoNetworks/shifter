-- Apply as the OpenFGA schema owner, after the released datastore migrations.
-- psql variables are login identifiers, never passwords or permission payloads.
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shifter_openfga_runtime') THEN
        CREATE ROLE shifter_openfga_runtime NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shifter_openfga_admin') THEN
        CREATE ROLE shifter_openfga_admin NOLOGIN;
    END IF;
    IF EXISTS (
        SELECT FROM pg_roles
        WHERE rolname IN ('shifter_openfga_runtime', 'shifter_openfga_admin')
          AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT FROM pg_auth_members m
        JOIN pg_roles r ON r.oid = m.member
        WHERE r.rolname IN ('shifter_openfga_runtime', 'shifter_openfga_admin')
    ) THEN
        RAISE EXCEPTION 'OpenFGA duty roles have unexpected inherited or elevated authority';
    END IF;
END $$;

-- Apply only to the dedicated OpenFGA database, never the application database.
SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO shifter_openfga_runtime, shifter_openfga_admin', current_database()) \gexec
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO shifter_openfga_runtime, shifter_openfga_admin;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Reconcile these owned role grants explicitly, including during upgrades.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM shifter_openfga_runtime, shifter_openfga_admin;
GRANT SELECT ON store, authorization_model, assertion, goose_db_version
    TO shifter_openfga_runtime;
-- FOR UPDATE tuple locking requires UPDATE as well as ordinary tuple DML.
GRANT SELECT, INSERT, UPDATE, DELETE ON tuple TO shifter_openfga_runtime;
GRANT SELECT, INSERT ON changelog TO shifter_openfga_runtime;

GRANT SELECT ON goose_db_version TO shifter_openfga_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON store, authorization_model, assertion, tuple, changelog
    TO shifter_openfga_admin;

GRANT shifter_openfga_runtime TO :"runtime_login";
GRANT shifter_openfga_admin TO :"admin_login";

-- Check effective authority after grants. Another membership (including one
-- reachable through SET ROLE) must not undo the separation above. Refuse drift
-- rather than removing an operator's independently assigned privileges.
SELECT set_config('shifter.openfga_runtime_login', :'runtime_login', true);
SELECT set_config('shifter.openfga_admin_login', :'admin_login', true);
DO $$
DECLARE
    runtime_name text := current_setting('shifter.openfga_runtime_login');
    admin_name text := current_setting('shifter.openfga_admin_login');
    login_name text;
BEGIN
    IF runtime_name = admin_name THEN
        RAISE EXCEPTION 'OpenFGA runtime and administration require distinct logins';
    END IF;
    FOREACH login_name IN ARRAY ARRAY[runtime_name, admin_name] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = login_name AND rolcanlogin)
           OR EXISTS (
               SELECT FROM pg_roles r
               WHERE pg_has_role(login_name, r.oid, 'MEMBER')
                 AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
                      OR has_schema_privilege(r.oid, 'public', 'CREATE')
                      OR has_database_privilege(r.oid, current_database(), 'CREATE')
                      OR has_table_privilege(r.oid, 'goose_db_version', 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
           ) THEN
            RAISE EXCEPTION 'OpenFGA API login has unexpected schema-owner or elevated authority';
        END IF;
    END LOOP;
    IF pg_has_role(runtime_name, 'shifter_openfga_admin', 'MEMBER') OR EXISTS (
        SELECT FROM pg_roles r
        CROSS JOIN unnest(ARRAY['store', 'authorization_model', 'assertion']) AS t(name)
        WHERE pg_has_role(runtime_name, r.oid, 'MEMBER')
          AND has_table_privilege(r.oid, t.name, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    ) THEN
        RAISE EXCEPTION 'OpenFGA runtime login has unexpected administration authority';
    END IF;
END $$;
COMMIT;
