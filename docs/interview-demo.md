# Interview Demo Script: ai-incident-commander

## Goal
Show end-to-end SRE incident response for a fintech payment API with AI-assisted RCA.

## 1) Baseline Health

```bash
make up
make health
make pay
make summary
```

Talking point:
- "In normal mode, the service accepts payment traffic and incident summary returns healthy-state RCA output."

## 2) Scenario A: Timeout Storm (Upstream Dependency Incident)

```bash
make timeout
python3 scripts/traffic_generator.py --duration 45 --concurrency 25 --rps 45
make summary
```

Talking point:
- "Timeout counters and failed requests climb quickly. The RCA summary highlights probable upstream timeout pressure and immediate mitigation steps."

## 3) Scenario B: DB Pool Exhaustion

```bash
make dbexhaust
python3 scripts/traffic_generator.py --duration 45 --concurrency 20 --rps 35
make summary
```

Talking point:
- "The system demonstrates a resource saturation failure pattern and quantifies impact with metric evidence."

## 4) Scenario C: Error Spike (Processor Fault)

```bash
make error
python3 scripts/traffic_generator.py --duration 30 --concurrency 20 --rps 40
make summary
```

Talking point:
- "Error spikes are captured in logs/metrics and the RCA summary proposes rollback + retry + alert hardening actions."

## 5) Recovery Validation

```bash
make normal
python3 scripts/traffic_generator.py --duration 20 --concurrency 10 --rps 20
make summary
```

Talking point:
- "I can prove stabilization and reduced error footprint after mitigation."
