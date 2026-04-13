FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server openssh-client sshpass \
    postgresql-client rsync git curl gnupg \
    python3 python3-flask python3-psycopg2 \
    ca-certificates coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

# Research analyst content lives in A16-research-analyst/ per convention;
# SSH keypair for the research-analyst account on A6 is pre-generated and
# stored under _shared/ so A6 can COPY the public half during its build.
COPY A16-research-analyst/dashboard.py /opt/research/dashboard.py
COPY A16-research-analyst/pgpass /opt/research/pgpass
COPY A16-research-analyst/ssh_config /opt/research/ssh_config
COPY A16-research-analyst/daily_integration_report.py /opt/research/daily_integration_report.py
COPY A16-research-analyst/ANALYST_TOKEN /opt/research/ANALYST_TOKEN
COPY _shared/research-analyst-key/id_rsa /opt/research/id_rsa
COPY _shared/research-analyst-key/id_rsa.pub /opt/research/id_rsa.pub

RUN chmod 644 /opt/research/dashboard.py /opt/research/ssh_config \
              /opt/research/daily_integration_report.py && \
    chmod 600 /opt/research/pgpass /opt/research/id_rsa /opt/research/ANALYST_TOKEN && \
    chmod 644 /opt/research/id_rsa.pub

COPY a16/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 8080
CMD ["/entrypoint.sh"]
