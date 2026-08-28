# ETH Monitor Agent Rules

## Sync token immutability

- `/etc/eth-monitor-api.env` is the production source of truth for `ETH_MONITOR_SYNC_TOKEN`.
- Treat the existing sync token as an immutable deployment secret.
- Never change, rotate, replace, reset, or regenerate it during deployment, publishing, debugging, recovery, or routine maintenance.
- Token rotation is allowed only when the user explicitly requests rotation in the current task and supplies or approves the new value.
- `server/update_sync_token.py` must remain locked behind `ETH_MONITOR_ALLOW_TOKEN_ROTATION=I_UNDERSTAND_THIS_ROTATES_SYNC_TOKEN`.
- Never commit the token value to Git, logs, documentation, JSONL state, or frontend source.
- Normal code deployment must preserve `/etc/eth-monitor-api.env` unchanged.
