---
description: Self-heal a failure - hand the raw error back and fix the root cause
argument-hint: <failing command>
---
# Heal

Failing command: $ARGUMENTS

Stack-trace hand-off: don't hand-fix symptoms; use the raw error as the prompt.
1. Run the command and capture the full output.
2. Find the first real failure (not the cascade). Read the code it points at.
3. `RESOLVE <error>`: make the smallest change that fixes the root cause. Never edit, skip or weaken a test to pass it.
4. Re-run the command. Repeat at most 3 times. If the same failure repeats twice, stop and report: you are not converging.
5. Report BLUF: fixed or not, the root cause in one sentence, files changed, final command output summary.

For unattended healing, wrap it in a Director config and run `/director`.
