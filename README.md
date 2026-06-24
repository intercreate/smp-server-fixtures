# SMP Server Fixtures

SMP (MCUmgr) **server** fixtures for testing SMP client transports —
[smpclient](https://github.com/intercreate/smpclient) and
[smpmgr](https://github.com/intercreate/smpmgr) — without physical hardware.

native_sim and QEMU fixtures run as ordinary processes, so a client test suite
can launch one as a subprocess and drive it with a real transport. Each release
ships a machine-readable [`manifest.json`](#manifest) describing every fixture.

## Fixtures

| Family | Targets | What it's for |
| --- | --- | --- |
| **Base** (`serial`, `serial_raw`, `udp`) | native_sim | Every command group the target can host; default buffers. |
| **Buffer-size matrix** (`serial_buf<N>`, `udp_buf<N>`) | native_sim, qemu | Sweep `buf_size` = 96, 128, 256, 400, 512, 1024, 2048 to validate fragmentation/reassembly and client buffer math (incl. a non-multiple of the line length and an edge below it). |
| **mps2 buffer matrix** (`serial_recovery_buf<N>`) | mps2 | The do-it-all recovery image (below) swept across `buf_size` = 400, 512, 1024, 2048. mps2's UART paces the link and its 4 MB SRAM clears the RAM ceiling, so it round-trips a real buffer-filling message — by echo, fs upload, or img (DFU) upload — at sizes where native_sim is bursty and qemu_cortex_m0 is too small. |
| **`serial_bigrx`** | native_sim | Default buffers but a large UART RX pool — receives full multi-fragment messages the small default pool would drop. |
| **`serial_line512`** | native_sim | Accepts long (512 B) serial frame lines, for non-default client line lengths. |
| **`serial_noparams`** | native_sim | MCUmgr params command disabled — exercises the client's fallback when `buf_size` can't be read. |
| **`shell`** | native_sim, mps2 | SMP over the Zephyr shell — SMP shares the UART with the shell prompt and logs. |
| **`udp6`** | native_sim | UDP over IPv6 (`[::1]:1337`). |
| **`serial_fs`, `udp_fs`** | native_sim | littlefs mounted at `/lfs1` for fs-group file upload/download. |
| **`serial`** (roomy) | mps2 | Cortex-M3, 4 MB SRAM via a flash overlay: one runnable image with **every** non-img group, fs file round-trips, and large buffers. |
| **`serial_recovery`** | mps2 | Do-it-all MCUboot RAM_LOAD image — boots **straight into the full app** (every group incl. img) serving SMP on uart0 and logging on uart1. `os reset boot_mode=1` re-enters MCUboot **serial recovery** on demand; an upload there persists across the soft reset (slots live in a non-erased RAM-backed flash simulator). Recovery advertises the MCUmgr params command, so a client can negotiate buffers against the bootloader (see `recovery_buf_size`). Launched with two QEMU loaders: the MCUboot `.hex` plus the `.signed.bin` dropped into slot0. |
| **`serial_recovery_raw`** | mps2 | The `serial_recovery` image, but both MCUboot recovery and the app speak the **raw** (non-console) SMP serial encoding — no base64/CRC/console framing, packets framed by the SMP header length (`CONFIG_BOOT_SERIAL_RAW_PROTOCOL` + `CONFIG_UART_MCUMGR_RAW_PROTOCOL`). For testing a client's raw serial transport against a real recovery server. Same two-loader launch as `serial_recovery`. |
| **`serial`** | qemu_cortex_m0 | Merged MCUboot + signed app — exercises the img (DFU) group under emulation. |
| **`serial`, `ble`, `serial_recovery`** | nrf52840dk | Build-only images for a hardware bench. |

The authoritative, per-release list (with each fixture's transport, buffers,
groups, and launch command) is the [manifest](#manifest). Fixtures are defined
in [`apps/smp-server/sample.yaml`](apps/smp-server/sample.yaml).

> The emulated `serial_recovery` / mps2 fixture is a single MCUboot RAM_LOAD
> image that boots **straight into the full app** (every group incl. img) and
> re-enters recovery on demand: `os reset boot_mode=1` (retained boot mode)
> drops back into MCUboot serial recovery, and an upload there persists across
> the soft reset because the image slots live in a non-erased RAM-backed flash
> simulator. See [Use a fixture](#use-a-fixture) for the two-loader launch.

## Get a fixture

Prebuilt fixtures are attached to GitHub releases as
`zephyr_<zephyr-version>_smp_server_<git-sha>_<target>_<config>.<ext>` with a
`SHA256SUMS` and a `manifest.json`. Extensions: `.exe` (native_sim), `.hex` (a
plain emulated image), `.merged.hex` (MCUboot + app), `.signed.bin` (the app
image to upload via the img group). Every build is kept as a permanent release
tagged by its commit SHA, and the newest is always marked as the repo's
[latest release](https://github.com/intercreate/smp-server-fixtures/releases/latest)
— so `releases/latest/download/manifest.json` always resolves the most recent
build. Download what you need, or build locally (below).

Each release is self-contained: a CI guard
([`validate_release.py`](.github/scripts/validate_release.py)) fails the publish
unless **every** asset carries that build's SHA and every image has a
`manifest.json` entry, so a release can't mix SHAs or ship a fixture the
manifest doesn't describe. Resolve the floating "latest" via GitHub's pointer
(`releases/latest/download/...`) or pin a specific build by its SHA tag (e.g.
`gh release download <sha>`) for a frozen reference. There is no rolling tag
literally named `latest`; the only "latest" is GitHub's own newest-release
pointer.

## Manifest

Each release includes `manifest.json`: an array with one entry per fixture, so a
client can build its test registry instead of hardcoding fixture rows. Fields:

| Field | Meaning |
| --- | --- |
| `artifact` | The fixture's filename in the release. |
| `target`, `config` | e.g. `native_sim`, `serial_buf256`. |
| `transport` | `serial`, `serial_raw`, `shell`, `udp`, or `bt`. |
| `ip_family` | `ipv4` / `ipv6` for UDP, else `null`. |
| `buf_size`, `buf_count` | The **app** SMP server's `CONFIG_MCUMGR_TRANSPORT_NETBUF_*`. |
| `recovery_buf_size`, `recovery_buf_count` | What the **bootloader's** serial-recovery server advertises via the MCUmgr params command (`CONFIG_BOOT_SERIAL_MAX_RECEIVE_SIZE`, a decoded ceiling, and always `1`) — what a client reads *while in recovery*, distinct from the app `buf_size`. `null` unless the image is a serial-recovery build with `CONFIG_BOOT_MGMT_MCUMGR_PARAMS=y`. |
| `line_length_max` | Max serial frame line the server accepts (`null` for non-serial). |
| `udp_port` | UDP listen port (`null` for non-UDP). |
| `groups` | Enabled MCUmgr command groups, e.g. `["os","stat","fs","enum"]`. |
| `mcuboot`, `serial_recovery` | Whether the image carries MCUboot / is a recovery image. |
| `run` | Launch command for native_sim (`null` otherwise). |
| `qemu_cmd` | QEMU launch command for emulated targets, with `<PORT>` to fill in (`null` otherwise). For the do-it-all `serial_recovery` / mps2 fixture this carries two `-device loader` entries (MCUboot `.hex` plus the app `.signed.bin` dropped into slot0). |

## Use a fixture

**Serial (native_sim)** prints its PTY path on boot:

```console
$ ./zephyr_*_native_sim_serial.exe
uart connected to pseudotty: /dev/pts/N
$ smpmgr --port /dev/pts/N os echo hello
```

**UDP (native_sim)** binds a host socket and logs readiness:

```console
$ ./zephyr_*_native_sim_udp.exe &
[...] <inf> smp_udp: Started (IPv4)        # udp6 fixtures log "(IPv6)"
$ smpmgr --ip 127.0.0.1 os echo hello      # udp6: --ip ::1
```

**QEMU** boots the image with its console UART on a chardev. For fragmented SMP
use a TCP socket (QEMU's emulated UART holds a frame's final byte over a PTY,
stalling reassembly) — this is the `qemu_cmd` form in the manifest, which
smpclient mirrors:

```console
$ qemu-system-arm -cpu cortex-m0 -machine microbit -nographic \
    -chardev socket,id=con,host=127.0.0.1,port=5555,server=on,wait=off \
    -serial chardev:con -monitor none \
    -device loader,file=zephyr_*_qemu_cortex_m0_serial.merged.hex
# connect your SMP client to 127.0.0.1:5555
```

For quick one-off commands a PTY works too:

```console
$ qemu-system-arm -cpu cortex-m0 -machine microbit -nographic \
    -chardev pty,id=con -serial chardev:con -monitor none \
    -device loader,file=zephyr_*_qemu_cortex_m0_serial.merged.hex
char device redirected to /dev/pts/N
$ smpmgr --port /dev/pts/N image state-read
```

**Do-it-all `serial_recovery` (mps2)** boots straight into the full app with two
loaders: MCUboot's code-only `.hex`, plus the signed app dropped directly into
slot0's flash-simulator backing store at SRAM `0x20050000`. uart0 is the SMP
transport (a TCP socket again, for fragmented SMP) and uart1 is the
console/boot/app log — QEMU maps the first `-serial` to uart0 and the second to
uart1:

```console
$ qemu-system-arm -cpu cortex-m3 -machine mps2-an385 -nographic \
    -chardev socket,id=smp,host=127.0.0.1,port=5555,server=on,wait=off \
    -serial chardev:smp \                                              # uart0 = SMP
    -serial file:/tmp/da_uart1.log \                                   # uart1 = console/log
    -monitor none \
    -device loader,file=zephyr_*_mps2_serial_recovery.hex \
    -device loader,file=zephyr_*_mps2_serial_recovery.signed.bin,addr=0x20050000
# connect your SMP client to 127.0.0.1:5555 — the app serves every group incl. img
```

Send `os reset boot_mode=1` (retained boot mode) to re-enter MCUboot serial
recovery; an upload there persists across the soft reset, since the slots live
in a non-erased RAM-backed flash simulator.

## Build locally

```bash
west twister -T apps --build-only -p native_sim -p qemu_cortex_m0 -p nrf52840dk/nrf52840
```

native_sim builds 32-bit; install `gcc-multilib` first.
