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
| **`serial_bigrx`** | native_sim | Default buffers but a large UART RX pool — receives full multi-fragment messages the small default pool would drop. |
| **`serial_line512`** | native_sim | Accepts long (512 B) serial frame lines, for non-default client line lengths. |
| **`serial_noparams`** | native_sim | MCUmgr params command disabled — exercises the client's fallback when `buf_size` can't be read. |
| **`shell`** | native_sim | SMP over the Zephyr shell — SMP shares the UART with the shell prompt and logs. |
| **`udp6`** | native_sim | UDP over IPv6 (`[::1]:1337`). |
| **`serial_fs`, `udp_fs`** | native_sim | littlefs mounted at `/lfs1` for fs-group file upload/download. |
| **`serial`** | qemu_cortex_m0 | Merged MCUboot + signed app — exercises the img (DFU) group under emulation. |
| **`serial`, `ble`, `serial_recovery`** | nrf52840dk | Build-only images for a hardware bench. `serial_recovery` is MCUboot serial recovery (the bootloader's own SMP server). |

The authoritative, per-release list (with each fixture's transport, buffers,
groups, and launch command) is the [manifest](#manifest). Fixtures are defined
in [`apps/smp-server/sample.yaml`](apps/smp-server/sample.yaml).

> **Not provided:** a *runnable* (emulated) MCUboot serial-recovery fixture — it
> doesn't fit the only MCUboot-capable QEMU target (nRF51, 16 KB RAM), so
> recovery ships build-only for hardware. SMP-over-shell ships native_sim only
> (it overflows the nRF51 QEMU).

## Get a fixture

Prebuilt fixtures are attached to GitHub releases as
`zephyr_<zephyr-version>_smp_server_<git-sha>_<target>_<config>.<ext>` with a
`SHA256SUMS` and a `manifest.json`. Extensions: `.exe` (native_sim), `.hex` (a
plain emulated image), `.merged.hex` (MCUboot + app), `.signed.bin` (the app
image to upload via the img group). The rolling
[`latest` release](https://github.com/intercreate/smp-server-fixtures/releases/tag/latest)
always tracks the newest build; every build is also kept as a permanent release
tagged by its commit SHA. Download what you need, or build locally (below).

## Manifest

Each release includes `manifest.json`: an array with one entry per fixture, so a
client can build its test registry instead of hardcoding fixture rows. Fields:

| Field | Meaning |
| --- | --- |
| `artifact` | The fixture's filename in the release. |
| `target`, `config` | e.g. `native_sim`, `serial_buf256`. |
| `transport` | `serial`, `serial_raw`, `shell`, `udp`, or `bt`. |
| `ip_family` | `ipv4` / `ipv6` for UDP, else `null`. |
| `buf_size`, `buf_count` | `CONFIG_MCUMGR_TRANSPORT_NETBUF_*`. |
| `line_length_max` | Max serial frame line the server accepts (`null` for non-serial). |
| `udp_port` | UDP listen port (`null` for non-UDP). |
| `groups` | Enabled MCUmgr command groups, e.g. `["os","stat","fs","enum"]`. |
| `mcuboot`, `serial_recovery` | Whether the image carries MCUboot / is a recovery image. |
| `run` | Launch command for native_sim (`null` otherwise). |
| `qemu_cmd` | QEMU launch command for emulated targets, with `<PORT>` to fill in (`null` otherwise). |

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

## Build locally

```bash
west twister -T apps --build-only -p native_sim -p qemu_cortex_m0 -p nrf52840dk/nrf52840
```

native_sim builds 32-bit; install `gcc-multilib` first.
