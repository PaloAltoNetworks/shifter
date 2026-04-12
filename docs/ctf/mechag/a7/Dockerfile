FROM gitea/gitea:1.23
COPY bootstrap.sh /app/bootstrap.sh
COPY bare-repos.tar.gz /app/bare-repos.tar.gz
RUN chmod +x /app/bootstrap.sh
EXPOSE 3000
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# Override the base image's ENTRYPOINT so we control the full startup
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
