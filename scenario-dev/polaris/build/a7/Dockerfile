FROM gitea/gitea:1.23
RUN apk add --no-cache python3 curl git bash
# bootstrap.sh and bare-repos.tar.gz live in A7-source-repo/ (content dir).
# Build context for this image is the parent mechag/ dir so COPY can reach both.
COPY A7-source-repo/bootstrap.sh /app/bootstrap.sh
COPY A7-source-repo/bare-repos.tar.gz /app/bare-repos.tar.gz
RUN chmod +x /app/bootstrap.sh
EXPOSE 3000
COPY a7/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# Override the base image's ENTRYPOINT so we control the full startup
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
