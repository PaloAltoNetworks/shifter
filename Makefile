.PHONY: gates

gates:
	node /home/atomik/src/Ground-Control/workflow/tools/run-gates.mjs --repo . --issue 1 --base origin/dev --head HEAD
