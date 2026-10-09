# LCP-002 — Generation Result And Termination Telemetry

Status: PROPOSED

LCP-002 defines the backend-neutral result object returned by model providers after a technically successful generation.

It does not change model behavior, prompts, schemas, generation budgets, provider failure taxonomy, OP-001 analytical semantics, or LCP-001 transport framing rules.

## LCP-002.1 — Problem

The current `ModelProvider.generate(...)` boundary returns only `str`.

That is sufficient for generated content, but it cannot cleanly propagate provider-owned execution metadata discovered at the model boundary.

The first real OP-001 baseline showed that:

- every `llama_cpp_cli` ModelRun can technically succeed while OP-001 still rejects malformed model content;
- `llama-completion.exe` can return partial generated stdout with exit code `0`;
- existing `ModelRun` provenance records configured inference parameters and timing, but cannot distinguish end-of-generation from other successful termination modes.

KCI needs a narrow provider result that carries generated content plus only reliable backend-neutral termination telemetry.

## LCP-002.2 — Generation Result

Proposed backend-neutral type:

```python
@dataclass(frozen=True)
class GenerationResult:
    content: str
    stop_reason: GenerationStopReason
    output_tokens: int | None
    provider_duration_ms: float | None
```

`GenerationResult` exists only for technically successful provider generation.

Provider failures continue to use the provider's existing typed failure path.

`GenerationResult` is not a parsed analytical result and is not trusted.

## LCP-002.3 — Stop Reason

Proposed v0.1 type:

```python
GenerationStopReason = Literal["eos", "unknown"]
```

`eos` means the provider observed a reliable backend signal that generation reached an end-of-generation or end-of-sequence condition.

`unknown` means the provider did not observe a reliable supported signal that can classify the successful termination more specifically.

Do not add `token_limit` or `context_limit` until a provider can reliably observe those states through a supported machine-readable signal.

Do not infer stop reason from timing, output length, JSON validity, malformed content, or operation-specific expectations.

## LCP-002.4 — Content

`content` is untrusted generated model content after provider-specific transport framing has been decoded.

It is not parsed analytical output.

It is not trusted.

It is not repaired JSON.

For `LlamaCppCliProvider`, `content` is stdout after applying the approved LCP-001 Deployment Amendment 2 rule for the exact terminal `llama-completion.exe` presentation sentinel:

```text
 [end of text]
```

LCP-002 does not broaden that rule.

Providers must not search for JSON, extract JSON objects or arrays, remove markdown fences, repair malformed JSON, infer missing fields, or otherwise convert malformed output into valid output.

## LCP-002.5 — LlamaCppCliProvider Mapping

For the currently supported `llama-completion.exe` non-interactive completion contract:

```text
raw stdout
    ->
inspect exact terminal llama.cpp framing
    ->
observed_eog = true/false
    ->
decode approved llama.cpp framing
    ->
GenerationResult
```

Mapping:

```text
exact terminal " [end of text]" sentinel observed before framing decode
    -> stop_reason = "eos"

exact terminal sentinel not observed
    -> stop_reason = "unknown"

generated token count
    -> output_tokens = None

provider wall-clock duration
    -> provider_duration_ms = existing provider-side duration
```

The provider must inspect only the exact terminal transport framing approved by LCP-001.

It must not inspect model semantics to determine stop reason.

It must not search arbitrary generated content for `[end of text]`.

Sentinel absence must not be interpreted as token-limit termination, context-limit termination, or malformed-output cause.

## LCP-002.6 — Output Tokens

`output_tokens` is the exact generated output token count if reliably supplied by the provider.

For current `LlamaCppCliProvider` v0.1:

```text
output_tokens = None
```

The provider must not retokenize stdout independently, parse unstable human-oriented stderr or performance text, estimate from character length, or persist raw output merely to derive a token count.

Existing `ModelRun.output_tokens` is the canonical destination for this value when available.

Do not duplicate output token fields.

## LCP-002.7 — ModelProvider Boundary

Current signature:

```python
def generate(
    self,
    task: str,
    context: dict[str, Any],
    output_schema: dict[str, Any],
    inference_parameters: dict[str, Any] | None = None,
) -> str:
    ...
```

Proposed signature:

```python
def generate(
    self,
    task: str,
    context: dict[str, Any],
    output_schema: dict[str, Any],
    inference_parameters: dict[str, Any] | None = None,
) -> GenerationResult:
    ...
```

The string-only result is too narrow for reliable provider metadata.

Do not keep an indefinite compatibility contract where providers may return either `str` or `GenerationResult`.

Migration should be explicit: all providers and test doubles return `GenerationResult`, and all callers consume `GenerationResult.content` for existing parsing behavior.

## LCP-002.8 — ModelRun Mapping

Conceptual mapping:

```text
GenerationResult.stop_reason
    -> ModelRun.stop_reason

GenerationResult.output_tokens
    -> ModelRun.output_tokens

GenerationResult.provider_duration_ms
    -> ModelRun.total_ms or existing provider-duration equivalent
```

Current `ModelRun` already has:

- `output_tokens`
- `total_ms`
- `input_tokens`
- `context_size`
- `model_load_ms`
- `prompt_eval_ms`
- `generation_ms`
- `prompt_tokens_per_second`
- `generation_tokens_per_second`
- `peak_memory_mb`

Current `ModelRun` does not have `stop_reason`.

Smallest persistence migration:

```sql
ALTER TABLE model_runs ADD COLUMN stop_reason TEXT;
```

Recommended value constraint at the contract/model layer:

```text
NULL | "eos" | "unknown"
```

Historical rows must remain `NULL`.

Do not backfill historical stop reasons by inference.

`ModelRun` remains backend-neutral. It must not contain llama.cpp-specific sentinel fields.

## LCP-002.9 — OP-001 Integration

OP-001 consumes:

```text
GenerationResult.content
```

for its existing strict parsing boundary.

OP-001 may pass backend-neutral generation metadata into `ModelRun` persistence through the existing execution boundary.

OP-001 must not:

- know about `[end of text]`;
- know about llama.cpp;
- infer token limits;
- parse stderr;
- reinterpret `stop_reason`;
- alter analytical behavior based on `stop_reason` in v0.1.

A valid response such as:

```json
{"patterns":[]}
```

remains a valid analytical result regardless of `stop_reason`.

Malformed model content remains malformed and continues through existing OP-001 parsing failure semantics.

## LCP-002.10 — Failure Semantics

`GenerationResult` is produced only after technical provider success.

Existing provider failures remain failures.

Do not convert:

```text
stop_reason = "unknown"
```

into provider failure.

Do not convert incomplete JSON into provider failure merely because `stop_reason` is `unknown`.

OP-001 strict parsing continues to determine whether generated content is usable for OP-001.

## LCP-002.11 — Migration Impact

Production callers affected:

- `src/kci/operations/uatu_op001.py`
  - `invoke_op001_model_boundary(...)` must receive `GenerationResult`.
  - It must parse `result.content`.
  - `_save_op001_model_run(...)` must persist backend-neutral metadata.

Provider implementations affected:

- `src/kci/models/base.py`
  - `ModelProvider.generate(...)` return type changes from `str` to `GenerationResult`.
- `src/kci/models/llama_cpp.py`
  - `LlamaCppCliProvider.generate(...)` returns `GenerationResult`.
  - Sentinel observation must occur before LCP-001 framing decode.
- `LlamaCppProvider`
  - inherits the same behavior.

Test doubles affected:

- `tests/test_op001_model_boundary.py`
  - `StubProvider` should return `GenerationResult`.
- `tests/test_llama_cpp_cli_provider.py`
  - provider-return assertions should inspect `result.content`, `result.stop_reason`, `result.output_tokens`, and `result.provider_duration_ms`.
- Any tests constructing or asserting `ModelRun` rows must account for nullable `stop_reason`.

Direct provider tests that currently expect a plain string should be migrated deliberately.

## LCP-002.12 — Compatibility

LCP-002 preserves:

- LCP-001 transport framing rules;
- raw model content remains untrusted;
- no JSON repair;
- no stderr-regex telemetry;
- no raw prompt/output canonical persistence;
- no chain-of-thought persistence;
- provider does not own `ModelRun` persistence;
- OP-001 remains backend-neutral;
- runtime remains responsible for Candidate to Insight promotion.

This proposal does not conflict with Contracts 001-008, OP-001, or LCP-001.

It refines the model provider execution boundary and `ModelRun` provenance path without changing analytical trust semantics.

## LCP-002.13 — Deferred

Explicitly deferred:

- `token_limit` stop reason;
- `context_limit` stop reason;
- generated token count for `llama-completion.exe`;
- tokenizer-based recounting;
- stderr/perf parsing;
- `llama-server`;
- llama.cpp source patches;
- prompt changes;
- OP-001 schema changes;
- generation-budget changes;
- analytical use of `stop_reason`;
- raw prompt/output persistence;
- chain-of-thought persistence.
