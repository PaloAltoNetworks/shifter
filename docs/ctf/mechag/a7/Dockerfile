FROM gitea/gitea:1.23
COPY bootstrap.sh /app/bootstrap.sh
COPY bare-repos.tar.gz /app/bare-repos.tar.gz
RUN chmod +x /app/bootstrap.sh
# Gitea runs on port 3000
EXPOSE 3000
# Custom entrypoint: start gitea, then bootstrap
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
