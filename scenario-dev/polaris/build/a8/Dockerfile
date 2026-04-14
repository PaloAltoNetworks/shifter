FROM postgres:16-alpine
# Init script lives in the content dir (A8-research-database/) per convention;
# build context is the parent mechag/ dir so COPY can reach it.
#
# The GPG private key for Vasik (flag 30 chain) is stored as base64 in the
# shared gpg-chain artifacts directory. It's substituted into the init SQL
# at build time so A8's compartment_b.key_storage row matches the keypair
# that A6 uses to encrypt full_integration_sim.mp4.gpg. Regenerating the
# keypair without rebuilding BOTH A6 and A8 will desync the chain.
COPY A8-research-database/01-init.sql /tmp/01-init.sql.template
COPY _shared/gpg-chain/vasik_private_b64.txt /tmp/vasik_private_b64.txt
RUN set -eu; \
    B64="$(tr -d '\n' < /tmp/vasik_private_b64.txt)"; \
    awk -v b64="$B64" '{gsub(/\{\{VASIK_PRIVATE_KEY_B64\}\}/, b64); print}' \
        /tmp/01-init.sql.template > /docker-entrypoint-initdb.d/01-init.sql; \
    if grep -q 'VASIK_PRIVATE_KEY_B64' /docker-entrypoint-initdb.d/01-init.sql; then \
        echo "ERROR: private key substitution failed"; exit 1; \
    fi; \
    rm /tmp/01-init.sql.template /tmp/vasik_private_b64.txt
ENV POSTGRES_PASSWORD=postgres
EXPOSE 5432
