# 0019. ESP-IDF provisioning is the heaviest, least locally-reproducible step of any target here

- Status: Accepted
- Related: [0003], [0018], [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 1008-1042 -->

**D19 — ESP-IDF provisioning is the heaviest, least locally-reproducible
step of any target here, and (until fixed) had no caching.**
`build-usermod-esp32`'s own header called this out directly: "No caching
yet... Left as a known follow-up, not forgotten."

Running the build itself inside a container is decided, not open: `esp32`
gets a Dockerfile under **D28**'s container-per-port migration that bakes
ESP-IDF into the image the same way `webassembly`'s Dockerfile bakes in
emsdk (**D16**'s own M8 precedent), not mounted from `cache_root()` —
explicitly not started yet (ESP-IDF is multi-gigabyte, the one remaining
real sizing question), tracked there.

One real environment finding worth keeping regardless of that: `openocd-esp32`
(part of ESP-IDF's own default toolset for a target, installed by
`install.sh esp32` regardless of what a usermod build actually needs it
for — flashing/JTAG debug, not building) failed its own post-install
check with `error while loading shared libraries: libusb-1.0.so.0`, in
this dev sandbox specifically. `apt install libusb-1.0-0` fixed it — an
ordinary Linux runtime dependency of upstream's own binary, already
present on any real dev machine or CI image (a GitHub-hosted runner
included).

What actually needed fixing was D19's own real complaint: **no caching**.
Landed as `usermod/espidf.py` — `fetch_esp_idf()`
caches the clone by version, `resolve_esp_idf()`'s own tool-install step
caches the toolchain + Python venv by `(version, idf_target)`, both via
the same `sources.cached_dir()` primitive `fetch_micropython()` already
uses (M1). `ResolvedEspIdf.env()` asks `idf_tools.py export --format
key-value` for the actual environment (`PATH`, `IDF_PYTHON_ENV_PATH`,
`OPENOCD_SCRIPTS`, `ESP_ROM_ELF_DIR`, ...) rather than reconstructing that
resolution by hand -- delegated, not reimplemented, matching `D2`. Not
`toolchains.py`'s `ToolchainSpec` shape, the same reason `emsdk.py` isn't
either (**D16**'s own M8 addendum): there is no single `<prefix>gcc` to
find on `PATH` here.
