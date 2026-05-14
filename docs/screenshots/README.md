# Screenshots

This directory is reserved for deployment proof and operational screenshots.

## Expected Contents (to be captured from a running deployment)

| Screenshot | Description |
|-----------|-------------|
| `healthz-response.png` | `/healthz` returning `{"status":"ok"}` |
| `readyz-response.png` | `/readyz` showing DB + Redis healthy |
| `metrics-output.png` | `/metrics` endpoint with Prometheus counters |
| `workflow-completed.png` | A workflow run in `completed` state |
| `escalation-flow.png` | Escalation claim/resolve sequence |
| `audit-verify-pass.png` | `opsctl audit verify` returning PASS |
| `dlq-list.png` | `opsctl queue dlq list` output |
| `ci-green.png` | GitHub Actions CI with all jobs passing |
| `compose-ps.png` | `docker compose ps` showing all services healthy |

## How to Capture

```bash
# Terminal screenshots can be captured with:
# macOS: Cmd+Shift+4 (area select)
# Linux: gnome-screenshot -a

# Or use script to capture terminal output as text:
script -q /dev/null -c "curl http://localhost:8000/healthz" > screenshots/healthz-output.txt
```

## CI Proof

The CI pipeline badge and latest run can be viewed at:
https://github.com/ramvadlamudi22-dev/insuranceops-ai/actions

All Phase 2A and Phase 4 PRs merged with green CI.
