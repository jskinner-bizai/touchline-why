# Dependency and model license review

The historical dependency review matched all 19 saved notices to the exact verified PyPI wheels, byte for byte. [`dependency-notice-audit.json`](dependency-notice-audit.json) retains those wheel and notice hashes. Its core hash identifies the M2 review baseline, not the final application source. The review itself changed no dependency, model or license. Final package hashes are recorded separately.

| Package | Pin | Shipped license declaration |
| --- | --- | --- |
| agent-framework-core | 1.22.0 | MIT, Microsoft notice verified |
| agent-framework-ollama | 1.0.0b261015 | MIT, Microsoft notice verified |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.19 | MPL-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| msgspec | 0.22.0 | BSD-3-Clause |
| ollama, Python client | 0.5.3 | MIT |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 declaration; full historical license chain retained |

The Microsoft PyPI license fields were empty; the MIT finding is based on actual shipped notices, not an inferred metadata value. Retain complete PSF/CNRI historical text rather than replacing it with one short label.

## Distribution conditions to preserve

| License family | Practical handling for this project |
| --- | --- |
| MIT, 10 packages | Retain copyright, permission and disclaimer text in copies/substantial portions. |
| BSD-3-Clause, 5 packages | Retain notices/conditions/disclaimer for source and binary distribution; do not imply endorsement. |
| Apache-2.0 | Keep the license, attribution and any applicable NOTICE material; identify changes if modifying covered files. It does not grant trademark rights. |
| CNRI/PSF historical chain | Keep the complete shipped license/history text and its applicable conditions. The short package metadata is not a replacement. |
| MPL-2.0, certifi | Keep covered-file notices and source availability when distributing covered executable material. A separate larger application can use its own license while satisfying the covered-file obligations. |

The offline judge ZIP includes the 19 pinned wheels under `wheelhouse/`, dependency notices and the hash lock. The GitHub source bundle keeps the notices and lock but excludes wheel binaries. Neither bundle includes model weights. Certifi's corresponding-source instructions are in [`CORRESPONDING_SOURCE.md`](CORRESPONDING_SOURCE.md). They retain the official pinned source URL and the recorded upstream archive digest; the source archive was not downloaded or locally hashed for this package. Preserve those instructions and the MPL notice when distributing the included wheel. The complete dependency set is not MIT.

Primary terms: [MIT](https://opensource.org/license/mit), [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0), [MPL 2.0 sections 3.1 to 3.4](https://www.mozilla.org/en-US/MPL/2.0/). The exact other notices are retained under `third_party/` and identified by the historical audit.

## Separate runtime and model

The historical local Ollama server reported version 0.40.5; its tagged project source has an official [MIT notice](https://github.com/ollama/ollama/blob/v0.40.5/LICENSE). That upstream source notice is linked rather than bundled here. Server binaries are not part of the proposed app distribution. The server-reported version has not been matched to a locally hashed build.

The existing custom `gemma4:12b` tag reports digest `6d26f29fb33332169db137f6b636ca40fb34d6c9069cb40dd7ca1df616e85791`, a backup parent and custom parameters. The digest is server-reported, not a fresh weight-file hash; the public catalog tag differed when the historical review was recorded. The installed license notice matches the saved Apache 2.0 text. [Google's Gemma 4 license](https://ai.google.dev/gemma/apache_2) and [official 12B model card](https://huggingface.co/google/gemma-4-12B-it) independently identify Apache 2.0. No model weights, downloader, new terms acceptance or license grant is proposed. Do not substitute the older Gemma terms for the separate Gemma 4 license.

The application still has no owner-approved license. See [`LICENSE_STATUS.md`](LICENSE_STATUS.md); approval and copyright authority remain open. Competition eligibility and public distribution permission remain separate decisions.
