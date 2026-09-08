# Ntake deterministic prompt evaluator

**Status:** Design approved for implementation.

## Purpose

`ntake-app` owns deterministic benchmark import, local target-model evaluation,
scoring, and reporting for LINK and PROPOSE prompt templates.

It does not author synthetic cases or prompt variants. The companion authoring
workflow lives in:

```text
../ntake-app-kiro/PROMPT_OPTIMIZER_AUTHORING.md
```

That workflow produces fictional benchmark source JSONL and stage-scoped variant
JSON files. This project consumes those files without any dependency on Kiro or
an external provider.

## Scope

The evaluator calls current prompt-facing production functions only:

```text
LINK
  build_link_prompt(...)
  -> LocalLlmClient.complete(...)
  -> parse_ids(...)

PROPOSE
  build_ntake_tools_view(REGISTRY)
  build_propose_prompt(...)
  build_tools_schema(REGISTRY)
  -> normalized action envelope
```

It MUST NOT start FastAPI, access the production database, invoke `/capture`,
run cron, retain real household traces, or modify production prompt source.
Existing product tests own state-to-prompt assembly, target attachment, confirmation,
and UI behavior.

## Persistent storage

Only reusable imported benchmarks are stored:

```text
prompt-optimizer/
  benchmarks/
    <benchmark_id>/
      manifest.json
      link.train.jsonl
      link.validate.jsonl
      propose.train.jsonl
      propose.validate.jsonl
```

The project owner chooses whether to commit, ignore, or remove benchmark files.
The evaluator MUST NOT modify `.gitignore` automatically.

`manifest.json` records:

```text
- benchmark ID and creation time;
- included stages and case counts;
- registry hash;
- source directory hash;
- accepted train/validation batch hashes;
- benchmark schema version;
- local target model ID, base URL, and timeout used for evaluation.
```

The evaluator saves no prompt variants, raw model replies, evaluations, or reports.
Command output is self-displaying; users may redirect stdout when they want to
retain a report.

Implementation source lives outside the runtime service:

```text
tools/prompt_optimizer/
```

## Benchmark case contract

A source benchmark contains fictional JSONL cases. Each case has a stage, a
fictional ID-bearing world, prompt inputs, required outputs, forbidden outputs,
and tags.

```json
{
  "case_id": "link-event-distractor-0001",
  "stage": "link",
  "tags": ["link.distractor_precision"],
  "timezone": "America/New_York",
  "now": "2026-09-04T18:25:00Z",
  "capture_author": "[m1] Alex (adult)",
  "world": {
    "members": [{"id": 1, "name": "Alex", "role": "adult"}],
    "work_items": [],
    "events": [{"id": 11, "title": "Piano recital"}]
  },
  "world_view": "FAMILY MEMBERS: ...",
  "deep_context": "RELEVANT EVENTS: ...",
  "capture": "can we move Sam's piano thing to Wed at 5?",
  "required_links": {
    "work_item_ids": [],
    "event_ids": [11],
    "member_ids": [2]
  },
  "forbidden_links": {"event_ids": [12]},
  "required_actions": [],
  "forbidden_actions": []
}
```

Labels are a synthetic oracle for prompt comparison. They are not a claim about
actual household intent.

## Deterministic validation

Before importing a source benchmark, code MUST reject cases when:

```text
- JSON does not match the case schema;
- required or forbidden IDs do not occur in the fictional world;
- required or forbidden actions do not exist in REGISTRY;
- required action params fail ActionSpec.accepts(...);
- required and forbidden labels overlap;
- the timestamp is not UTC ISO-8601 or timezone is not an IANA zone;
- capture text contains internal IDs or action/tool names;
- world_view omits declared entity ID tokens;
- duplicate case fingerprints occur.
```

The action registry is a grammar constraint. It validates action names and
parameter shapes but does not decide semantic household intent.

## Metrics and selection

```text
LINK objective:
  maximize required-ID recall
  maximize forbidden-ID precision

PROPOSE objective:
  maximize required-action recall
  maximize forbidden-action precision
```

The scorer canonicalizes action calls as `(name, canonical_json(params))` and
scores action order as irrelevant while preserving duplicates. Every unexpected ID
or action call is a false positive.

The report includes:

```text
- required recall;
- forbidden precision;
- action parameter exactness;
- participant/time accuracy;
- no_action true-negative rate;
- per-tag metrics;
- local target-model latency.
```

For one stage, train winner selection is deterministic:

```text
1. Reject a variant that lowers forbidden precision on train.
2. Maximize required recall on train.
3. Prefer lower latency when quality ties.
4. Report validation metrics for the selected train winner.
```

Validation metrics are an independent check. They do not influence train winner
selection.

## Stage boundaries

LINK and PROPOSE run independently:

```text
STAGE=link
- varies only LINK_SYSTEM and LINK_CONTEXT;
- evaluates link.train.jsonl and link.validate.jsonl.

STAGE=propose
- varies only PROPOSE_SYSTEM and PROPOSE_CONTEXT;
- evaluates propose.train.jsonl and propose.validate.jsonl.
```

The evaluator MUST NOT combine LINK and PROPOSE variants by default because their
cross product hides prompt attribution. `STAGE=both` is valid only for benchmark
import and stores independent stage case sets.

## Prompt override worker

The control is the unmodified committed prompt. A variant is a full replacement
template supplied in an external variants JSON file.

Each variant runs in a separate process that:

```text
1. imports the existing LINK or PROPOSE prompt module;
2. saves the original module template constant;
3. temporarily replaces the selected stage template;
4. calls the existing production prompt builder and schema;
5. calls the local target model through LocalLlmClient;
6. restores the original template in a finally block and exits.
```

A deterministic test MUST prove the control worker renders current prompt snapshot
text unchanged.

## Make interface

```bash
# Import an externally authored fictional benchmark source directory.
make prompt MODE=benchmark STAGE=both \
  SOURCE=../ntake-app-kiro/generated/benchmarks/<name>

# Evaluate the local target model on control and externally authored link variants.
make prompt MODE=evaluate \
  STAGE=link \
  BENCHMARK=<benchmark_id> \
  VARIANTS_FILE=../ntake-app-kiro/generated/variants/<name>-link.json
```

`MODE=evaluate` MUST:

```text
- add the control prompt if the variants file omits it;
- run control and every stage-matching variant on both train and validation;
- select using train metrics only;
- print one self-displaying report with metric deltas and selected winner;
- save no evaluation state.
```

## Implementation task list

### 1. Deterministic external tool code

`tools/prompt_optimizer/` contains:

```text
types.py       case, benchmark, variant, score, and result models
validate.py    schema, ID, registry, time, contradiction, and duplicate checks
score.py       LINK/PROPOSE canonicalization, metrics, and winner selection
benchmark.py   JSONL import, manifest, hashes, and project storage
worker.py      isolated local target-model template override worker
cli.py         benchmark import and evaluation dispatch
```

Tests MUST use `ScriptedLLM` or a local mock transport. No test requires an
external authoring model.

### 2. Benchmark import

`make prompt MODE=benchmark` imports source JSONL, validates it, writes benchmark
state, and prints the benchmark path. It MUST NOT generate or review cases.

### 3. Evaluation

`make prompt MODE=evaluate` evaluates one stage with the local target model,
control, and supplied variants file. It prints deterministic metrics and does not
write prompt source.

### 4. Human adoption

A human manually applies any selected template change to production source, then
runs `make check` and repeats evaluation with the committed control prompt.

## Definition of done

```text
- ntake-app contains no authoring-agent, Kiro, or external-provider code.
- Imported benchmarks are the only persistent evaluator state.
- LINK and PROPOSE are independently stage-scoped.
- One Make target imports benchmarks and evaluates variants.
- Control and all variants run against both train and validation.
- Selection uses train metrics only; validation is an independent report.
- Normal tests remain deterministic and offline.
- No production database, real household data, cron, or automatic prompt adoption
  is used.
```
