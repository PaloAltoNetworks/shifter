Deflake the built-image stack-smoke job's `SKIP_MIGRATIONS` assertion. The
web container's "Skipping migrations" log line is emitted by `entrypoint.sh`
before it execs the server, but docker log delivery for that early output can
lag the readiness probe on a busy runner, so the single-shot
`docker logs | grep` check raced and intermittently failed
(`SKIP_MIGRATIONS contract broken`). The assertion now polls with a bounded
deadline (`SMOKE_LOG_ASSERT_TIMEOUT`, like the script's other `wait_for`
checks); a genuine contract break still fails because the entrypoint logs
"Running migrations" instead.
