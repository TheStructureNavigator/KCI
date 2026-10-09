# LCP-001 — llama.cpp CLI Provider

Status: IMPLEMENTED

Concrete provider:

```text
LlamaCppCliProvider
```

Logical provider identity:

```text
llama_cpp_cli
```

## LCP-001.1 — Responsibility And Boundary

`LlamaCppCliProvider` is an infrastructure implementation of `ModelProvider`.

Its responsibility is:

```text
generic model request
    -> local llama.cpp CLI invocation
    -> technical model response/failure
```

It must not understand or import analytical/domain concepts such as Finding, Insight, InsightCandidate, IntelligenceContext, Uatu semantics, OP-001 model input, OP-001 model patterns, `pattern_type`, or significance.

It must not select a model, silently change a model, perform fallback, own a repository, persist ModelRun, reconstruct KCI/KCC data, or expand model input.

GGUF and llama.cpp CLI concepts belong to this concrete provider, not to the generic `ModelProvider` abstraction.

The provider is named `LlamaCppCliProvider` so future llama.cpp transports, such as a persistent server provider, can have separate semantics.

## LCP-001.2 — Process Invocation

Deployment Amendment 1 changes the v0.1 reference process interface to:

```text
llama-completion.exe
```

Reason: real Qwen3 deployment testing showed a chat-template / JSON-grammar collision in `llama-cli`, while `llama-completion.exe` with explicit `--no-conversation` successfully performed schema-constrained raw completion. Non-interactive `llama-completion.exe` accepts the prompt through `--prompt` / `-p`, not stdin.

Deployment Amendment 2 records that `llama-completion.exe` appends a terminal presentation sentinel to stdout after end-of-generation:

```text
 [end of text]
```

This exact terminal sentinel is llama.cpp transport framing, not model-generated content. `LlamaCppCliProvider` may remove only this exact terminal framing from stdout returned by a technically successful `llama-completion.exe` process. The remaining content is still untrusted raw model output.

Each invocation runs the configured llama.cpp completion executable as a direct child process.

Requirements:

- `shell=False`
- no `cmd.exe` / PowerShell wrapper
- no `os.system`
- executable path explicitly configured
- model path explicitly configured
- fail fast if required local artifacts do not exist
- no PATH-based model/runtime discovery
- dynamic model request passed as one UTF-8 argv value through `--prompt` / `-p`
- stdin is not used as an interactive prompt channel
- no temporary prompt file by default
- argv contains execution configuration plus the approved non-interactive `--prompt` request value
- `--offline` is present
- `--no-conversation` is present
- `--no-display-prompt` is present
- stdout and stderr captured separately
- stdout is the technical generated response after any exact terminal `llama-completion.exe` presentation framing is decoded
- stderr is diagnostics
- exit code other than zero is provider execution failure
- exit code zero means only technical process completion
- timeout terminates/kills and reaps the child process through the subprocess timeout mechanism
- no semantic dependency on current working directory
- no hidden environment variable controls analytical behavior

Generic structured-output constraints are translated to llama.cpp CLI arguments.

The provider continues to pass the serialized output schema inline as one argv element following:

```text
--json-schema
```

It does not create a temporary schema file by default. Inline `--json-schema` through Python `subprocess.run([...], shell=False)` has been successfully verified against the real local `llama-completion.exe` runtime. Full `LlamaCppCliProvider` real-runtime verification remains pending until the provider smoke is repeated successfully after Deployment Amendment 2.

## LCP-001.3 — Configuration And Model Artifact Identity

Each inference exposes enough technical provenance to identify:

- logical provider identity
- llama.cpp runtime/build identity when reliably available
- exact model artifact identity
- effective inference parameters
- execution timing

Local executable/model paths are deployment configuration, not canonical identity.

The concrete GGUF artifact is identified by SHA-256.

The provider computes the GGUF SHA-256 during initialization and reuses it for invocations. It does not hash the model for every ModelRun.

Filename may be exposed as supplementary human-readable model name, but it does not replace artifact hash identity.

Runtime/build identity is represented honestly. In v0.1 it is `unknown` unless a reliable runtime metadata source is added later. The provider does not infer a version from directory or file names.

LCP-001 does not hash the llama.cpp executable in v0.1.

Behavior- and execution-affecting inference parameters actually used by an invocation are surfaced through existing ModelRun inference-parameter persistence.

LCP-001 does not create a model registry.

## LCP-001.4 — Structured Generation Boundary

The generic provider boundary accepts a backend-agnostic output schema.

`LlamaCppCliProvider` translates that required schema to llama.cpp CLI structured generation using `--json-schema`.

If a required structured-output constraint cannot be applied, the provider fails explicitly with category `configuration`.

It must never silently degrade to unconstrained generation, prompt-only "please return JSON", or regex-based output extraction.

llama.cpp constrained generation guarantees or assists structure only.

It does not establish analytical correctness, support correctness, Finding membership, subject grounding, significance correctness, or trust.

The provider returns an untrusted raw response.

For `llama-completion.exe`, the provider performs only the approved transport-framing decode for the exact terminal presentation sentinel:

```text
 [end of text]
```

If this sentinel is present only as terminal framing of stdout from a successful process, the provider removes that terminal framing before returning the untrusted response. If deterministic terminal newline characters immediately follow the sentinel, they are treated as part of the same llama.cpp presentation framing. A successful process without the sentinel returns stdout unchanged.

The provider must not search for JSON, extract the first object or array, remove markdown fences, repair malformed JSON, repair punctuation or brackets, infer missing fields, remove non-terminal sentinel occurrences, remove sentinel text inside generated content, or otherwise convert malformed output into valid output.

The provider must not parse operation-specific types such as `Op001ModelResponse`.

OP-001 remains responsible for strict output parsing, support validation, subject grounding, and analytical semantics.

Runtime remains responsible for Candidate to trusted Insight promotion.

The provider does not repair malformed output and does not introduce SchemaRegistry or capability-negotiation infrastructure.

## LCP-001.5 — Failure Taxonomy And Diagnostics

The provider uses a small stable failure taxonomy:

- `configuration`
- `process_start`
- `timeout`
- `process_execution`
- `provider_internal`

`configuration` means invalid/missing required configuration or local artifact, or a required output constraint cannot be applied.

`process_start` means configuration was sufficient to attempt execution but the operating system could not start the process.

`timeout` means the process started but exceeded the explicit invocation timeout.

`process_execution` means the process started and terminated with a technical execution failure, especially non-zero exit code.

`provider_internal` means provider implementation failure that cannot honestly be classified above.

The provider does not establish canonical failure categories by parsing mutable human-readable stderr strings.

stderr is diagnostics, not KCI failure semantics.

Malformed or analytically invalid model output after successful process execution is not a provider failure. OP-001.9 semantics continue to apply.

Provider errors are typed and expose the stable category. Diagnostics may include bounded message, exit code, duration, and bounded stderr excerpt.

Raw dynamic input/output is not persisted by default.

Failure must not trigger retry, model fallback, quantization change, CPU/GPU switch, context reduction, timeout modification, or dropping structured-output constraints.

## LCP-001.6 — Offline And Security

Inference is local-only.

The provider uses explicitly configured local executable, explicitly configured local GGUF, and local CPU/GPU resources.

The provider must not download models, download tokenizer/template artifacts, resolve remote model IDs, contact Hugging Face, call external APIs, perform update checks, report usage, send telemetry externally, or otherwise require network access for inference.

Missing local artifacts cause failure, never automatic download.

Dynamic request data is not intentionally persisted by the provider.

The provider does not create prompt/request/debug files by default.

stdout and stderr are potentially sensitive dynamic content and must not be blindly dumped into logs.

This contract guarantees local-only technical inference behavior. It does not declare arbitrary company/HR data approved for processing.

## LCP-001.7 — Lifecycle, Concurrency And Resource Ownership

v0.1 uses:

```text
one invocation = one fresh llama-completion child process
```

There is no persistent inference process.

The provider owns the lifecycle of every process it starts:

```text
spawn -> communicate -> normal exit
```

or:

```text
spawn -> timeout/error -> terminate/kill -> reap
```

A single `LlamaCppCliProvider` instance supports at most one active inference at a time. Concurrent invocation is rejected.

LCP-001 does not add a queue, worker pool, broker, global hardware resource manager, or canonical queued/waiting states.

Concurrency policy does not leak into OP-001 semantics.

Timeout support is required.

General external cancellation API is deferred.

There is no dynamic resource fallback after OOM or other resource failure.

Model loading on each CLI invocation is intentional in v0.1 and is part of measured end-to-end cost.

This provider is not optimized into llama-server or persistent model loading.

## LCP-001.8 — Observability And Benchmark Metrics

Each provider invocation exposes provider-side wall-clock duration measured by KCI using a monotonic clock.

This duration represents real CLI invocation cost, including process startup, model loading, prompt processing, generation, and process termination where applicable.

The primary provider duration is not derived from llama.cpp stderr.

Runtime-specific metrics may be supplementary only when obtained reliably.

Absence of optional runtime metrics is not failure.

The provider does not guess token counts with an unrelated tokenizer and does not create brittle canonical behavior based on regex parsing unstable human-readable stderr.

Required/common metric:

```text
provider_duration_ms
```

Provider telemetry must not affect InsightCandidate, significance, Finding/Insight semantics, or trust decisions.

End-to-end IntelligenceRun timing remains separate from provider timing.

LCP-001 does not add Prometheus, Grafana, OpenTelemetry infrastructure, metrics server, or dashboard.
