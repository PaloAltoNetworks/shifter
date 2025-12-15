1. Explicit Tool Call Verification
Add a requirement like:

"After using a tool, always verify you received actual output in the tool result before describing what happened. If a tool call fails or returns an error, acknowledge it immediately rather than assuming success."
"Never describe tool results you didn't actually receive. If you're uncertain whether a tool executed successfully, check the tool result tags explicitly."
2. Error Handling Priority
Add guidance such as:

"When a tool returns an error, immediately report the error to the user. Do not attempt to work around it silently or pretend the operation succeeded."
"If you receive a 500 error or tool failure, stop and inform the user before attempting alternative approaches."
3. Output Grounding Rules
Include something like:

"Only describe file contents, command outputs, or system states that are explicitly present in tool results. Never infer, assume, or generate plausible-sounding outputs."
"When asked 'what are the results', quote or paraphrase directly from the most recent relevant tool output rather than reconstructing from memory."
4. Tool Selection Clarity
Add explicit reminders:

"When multiple tools can accomplish a task (e.g., kali_session_command vs kali_run_command), if the user specifies which tool to use, always use that exact tool."
"Pay close attention to tool name differences. Similar-sounding tools may have different behaviors (e.g., kali_close_session vs kali_close_persistent_session)."
5. Session State Awareness
Include guidance like:

"Track which sessions are active. Before using a session-based tool, verify the session exists or create it first."
"When asked about background or persistent sessions, explicitly check their status rather than assuming they're still active."
