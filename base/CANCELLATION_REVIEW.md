# Timeout cancellation evidence

The observed M2 timeout clients and owned transports closed. This is client-side evidence. Actual server-side generation cancellation, its completion time and GPU work cessation were not measured. A later `/api/ps` entry shows residency, not an idle or cancellation acknowledgement. This documentation review made no new live model call, model-service request or server-log search.

## What the primary source supports

Go's [HTTP Request.Context documentation](https://pkg.go.dev/net/http#Request.Context) says that an incoming request context is cancelled when its connection closes, when an HTTP/2 request is cancelled, or when its handler returns. Ollama's [tagged v0.40.5 ChatHandler](https://github.com/ollama/ollama/blob/v0.40.5/server/routes.go) passes the HTTP request context into scheduling and native chat execution; its other completion path derives a cancellable context from it. This supports an expectation of cooperative cancellation propagation. It does not measure the deployed runner or establish a maximum time to halt hardware work.

The tagged [chat handler](https://github.com/ollama/ollama/blob/v0.40.5/server/routes.go), [model-server interface](https://github.com/ollama/ollama/blob/v0.40.5/llm/server.go) and [MIT notice](https://github.com/ollama/ollama/blob/v0.40.5/LICENSE) are available at these official pinned upstream links. Those source files and the earlier review's source-provenance record are not bundled in this capsule. The server only reported version 0.40.5; its deployed binary was not independently matched to that source. An interface accepting contexts does not itself prove every backend's cancellation behavior.

The included [M2 measurement summary](evidence/m2-model-measurements.json) records the four historical real local calls, including both timeout cleanup results. Its references to the first and second raw timeout receipts identify historical records; those two raw receipt files are not bundled here. The two accepted raw selection receipts are included separately. This review does not change any receipt bytes.

## Mock lifecycle evidence

The included [`mock_lifecycle_test.py`](mock_lifecycle_test.py) uses the actual SDK/native adapter with an injected transport, never a real server. Both tests observe a timeout and successful owned-client/transport closure. A cooperative fake backend stops on disconnect. An independent fake backend remains active until explicit test cleanup, despite the same successful client closure. Both tests passed in the recorded M3 review; that result is not a new run against later source changes. This demonstrates why the client observation alone cannot establish the backend outcome; it is not a measurement of Ollama.

The tests retain the adapter's explicit `server_cancellation: not measured; no cancellation claim` result. They spend zero real model calls. All fake background tasks are positively owned and stopped during test teardown.

## Defensible published wording

`The client deadline expired and its owned HTTP client and transport closed. The deployed model server's cancellation and compute-stop timing remain unverified.`

A stronger claim would require a separately authorized controlled measurement with request correlation, server/runner acknowledgement and timing evidence, plus proof no stale result can be applied. It cannot be inferred from closed client sockets, source inspection or model residency. The historical M2 call budget was exhausted; this package adds no such measurement.
