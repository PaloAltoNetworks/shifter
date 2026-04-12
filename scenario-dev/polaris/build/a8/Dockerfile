FROM postgres:16-alpine
# Init script lives in the content dir (A8-research-database/) per convention;
# build context is the parent mechag/ dir so COPY can reach it.
COPY A8-research-database/01-init.sql /docker-entrypoint-initdb.d/01-init.sql
ENV POSTGRES_PASSWORD=postgres
EXPOSE 5432
