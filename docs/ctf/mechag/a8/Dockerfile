FROM postgres:16-alpine
COPY 01-init.sql /docker-entrypoint-initdb.d/01-init.sql
ENV POSTGRES_PASSWORD=postgres
EXPOSE 5432
