Make the terminal session-capacity test suites deterministic under
parallel (`-n auto`) execution. `TerminalSessionRegistry` gains a `reset()`
lifecycle helper, and both the ASGI real-stack integration suite and the
SSH-consumer-capacity suite now reset the canonical
`mission_control.terminal_sessions.session_registry` singleton in place
between tests instead of rebinding the consumer's alias to throwaway
instances. The old approach left a registry decoupled from the consumer
alias on the xdist worker, which made the per-process session-cap test
intermittently fail (it passed only serially).
