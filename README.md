# SMP Server Fixtures

SMP (MCUmgr) **server** fixtures for testing SMP client transports —
[smpclient](https://github.com/intercreate/smpclient) and
[smpmgr](https://github.com/intercreate/smpmgr) — without physical hardware.

Each fixture enables every MCUmgr command group available on its target, so a
single fixture can exercise any command.

## Fixtures

| Fixture | Target | Transport | Artifact |
| --- | --- | --- | --- |
| `serial.native_sim` | native_sim | serial (host PTY) | `.exe` |
| `serial_raw.native_sim` | native_sim | raw UART | `.exe` |
| `udp.native_sim` | native_sim | UDP, `127.0.0.1:1337` | `.exe` |
| `serial.qemu_cortex_m0` | QEMU | serial (host PTY) + DFU | `.hex` |
| `serial.nrf52840dk` | hardware | serial + DFU | `.hex`, `.signed.bin` |
| `ble.nrf52840dk` | hardware | BLE + DFU | `.hex`, `.signed.bin` |

The native_sim and QEMU fixtures run in software; the hardware fixtures are
images to flash on a bench.

## Get a fixture

Prebuilt fixtures are attached to the rolling
[`latest` release](https://github.com/intercreate/smp-server-fixtures/releases/tag/latest)
as `smp_server_<zephyr-version>_<fixture>.{exe,hex,signed.bin}` with a
`SHA256SUMS`. Download the one you need, or build locally (below).

## Use a fixture

**Serial (native_sim)** prints its PTY path on boot:

```console
$ ./smp_server_<ver>_serial_native_sim.exe
uart connected to pseudotty: /dev/pts/N
$ smpmgr --port /dev/pts/N os echo hello
```

**UDP (native_sim)** binds a host socket:

```console
$ ./smp_server_<ver>_udp_native_sim.exe &
$ smpmgr --ip 127.0.0.1 os echo hello
```

**QEMU (DFU)** boots a merged MCUboot + app image with its console on a PTY:

```console
$ qemu-system-arm -cpu cortex-m0 -machine microbit -nographic \
    -chardev pty,id=con,mux=on -serial chardev:con \
    -device loader,file=smp_server_<ver>_serial_qemu_cortex_m0.hex
char device redirected to /dev/pts/N
$ smpmgr --port /dev/pts/N image state-read
```

## Build locally

```bash
west twister -T apps --build-only -p native_sim -p qemu_cortex_m0 -p nrf52840dk/nrf52840
```

native_sim builds 32-bit; install `gcc-multilib` first. Fixtures are defined in
[`apps/smp-server/sample.yaml`](apps/smp-server/sample.yaml).
