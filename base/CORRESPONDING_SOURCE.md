# Corresponding source for the included certifi wheel

The offline judge ZIP includes the unmodified `certifi==2026.10.19` wheel at `wheelhouse/certifi-2026.10.19-py3-none-any.whl` under its existing MPL-2.0 terms. The GitHub source bundle excludes wheel binaries. Both bundles retain the original license at [`third_party/certifi-2026.10.19/LICENSE`](third_party/certifi-2026.10.19/LICENSE). The larger application has a separate, unresolved application license decision.

Corresponding source is available from the upstream PyPI source distribution:

- [certifi 2026.10.19 source archive](https://files.pythonhosted.org/packages/a6/bd/1436c50cc46699de0230fbaacc1d1de7bfec413176099949e9d5112e88f2/certifi-2026.10.19.tar.gz)
- Filename: `certifi-2026.10.19.tar.gz`
- Source-archive SHA-256 recorded in the upstream release metadata (not a local verification of downloaded source bytes): `035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae`
- Upstream project: [python-certifi](https://github.com/certifi/python-certifi)
- Release metadata: [PyPI certifi 2026.10.19](https://pypi.org/pypi/certifi/2026.10.19/json)

The source archive was not downloaded as part of this packaging task. Its URL and digest were taken from previously collected upstream release metadata, available at the official PyPI metadata link above; a copy of that metadata is not included here. The archive digest is therefore a recorded upstream value, not a locally verified source-archive hash. The included wheel has a separate digest recorded in [`DEPENDENCY_MANIFEST.json`](DEPENDENCY_MANIFEST.json) and [`requirements.lock`](requirements.lock). Package installation uses only the included wheel files and does not fetch this source archive.
