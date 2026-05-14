# Demo Video Guide

## 2-Minute Showcase Walkthrough

Target audience: Engineering managers, portfolio reviewers, potential collaborators.

### Script

| Time | Action | What to show |
|------|--------|--------------|
| 0:00-0:10 | Intro | "InsuranceOps AI: production-grade AI-assisted workflow orchestration for insurance operations" |
| 0:10-0:25 | Architecture | Show README Mermaid diagram: single image, Postgres source of truth, Redis queue, audit chain |
| 0:25-0:40 | Boot stack | `docker compose up -d` + `curl /healthz` + `curl /readyz` |
| 0:40-0:55 | Ingest + Run | Upload sample claim, start workflow, poll to `completed` |
| 0:55-1:10 | Audit trail | Query events endpoint, show hash-chained sequence |
| 1:10-1:20 | AI extraction | Show `ai_metadata` in step output (OCR, confidence, provider tracking) |
| 1:20-1:35 | Escalation | Upload invalid doc, show `awaiting_human`, claim + resolve |
| 1:35-1:50 | Ops tooling | `opsctl audit verify-batch`, `opsctl queue dlq count`, backup script |
| 1:50-2:00 | Close | "Full CI green, 113 files lint-clean, 50+ tests, deterministic replay" |

### Terminal Commands (copy-paste ready)

```bash
# Boot
docker compose -f compose/compose.yml up -d
docker compose -f compose/compose.yml ps

# Health
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# Seed key
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py
export TOKEN="<from output>"

# Ingest
curl -s -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@docs/demo-assets/sample_auto_claim.txt;type=text/plain" | jq .

# Workflow
export DOC_ID="<from above>"
curl -s -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"workflow_name\":\"claim_intake\",\"document_ids\":[\"${DOC_ID}\"],\"inputs\":{}}" | jq .

export RUN_ID="<from above>"

# Poll
curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID} \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state, version}'

# Audit
curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID}/events \
  -H "Authorization: Bearer ${TOKEN}" | jq '.events[] | {seq_in_run, event_type}'

# Verify
./scripts/opsctl audit verify --workflow-run-id ${RUN_ID}

# Metrics
curl -s http://localhost:8000/metrics | grep workflow_runs
```

## Full Demo Walkthrough (5 minutes)

For deeper technical demonstrations:

| Time | Scenario | Key Points |
|------|----------|------------|
| 0:00-1:00 | Happy path | Full lifecycle: ingest -> extract (with AI metadata) -> validate -> route -> complete |
| 1:00-2:00 | Escalation | Invalid policy number, escalation creation, operator claim/resolve, workflow resumption |
| 2:00-3:00 | AI capabilities | Show OCR provider call in logs, confidence scoring, review routing decision, summarization output |
| 3:00-4:00 | Operations | DLQ inspection, batch audit verification, backup/restore drill, rate limiting demo |
| 4:00-5:00 | Architecture | Walk through code structure, show tests passing, explain audit chain, show metrics |

## Recording Tips

1. **Terminal**: Use a dark theme with 14pt+ font for readability
2. **JSON output**: Always pipe through `jq .` for formatting
3. **Timing**: Pre-run commands once to populate any caches; demo runs should be smooth
4. **Reset**: Start with `docker compose down -v && docker compose up -d` for a clean slate
5. **Focus**: Show one thing at a time; don't scroll past output too quickly

## Recommended Tools

- **Terminal recording**: [asciinema](https://asciinema.org/) for shareable terminal recordings
- **Screen recording**: OBS Studio or QuickTime (macOS)
- **GIF generation**: `asciinema rec demo.cast && agg demo.cast demo.gif`

## Key Talking Points

1. **Not a prototype** — full CI pipeline, migration safety, backup/restore, rate limiting
2. **Deterministic by design** — mock providers produce same output for same input; replay-safe
3. **Fail-safe AI** — AI operations never crash the workflow; graceful degradation on error
4. **Audit integrity** — hash-chained events, tamper detection, scheduled verification
5. **Operational maturity** — DLQ tooling, batch verification, backup drills, monitoring
6. **No vendor lock-in** — protocol-based AI providers; swap from mock to real with config only
