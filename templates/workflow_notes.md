# Workflow / Architecture Notes

Use this page as a scratch template; you may replace it with your own diagram.

```text
Purchase Request
      |
      v
Understand request
      |
      v
Gather evidence ----> Business data / APIs / policy
      |
      v
Deterministic checks ----> thresholds / budget / required fields
      |
      v
Reason about policy & risk
      |
      v
Structured recommendation
      |
      v
Human review / approval
```

Document:
- your tools,
- what is deterministic vs. model-driven,
- agent responsibilities,
- handoff format,
- stop/escalation conditions,
- what you intentionally did not build.
