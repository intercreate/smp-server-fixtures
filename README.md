# Simple Management Protocol (SMP) Server Fixtures

This repository provides SMP server fixtures for testing SMP client tools like [smpmgr](https://github.com/intercreate/smpmgr) and [smpclient](https://github.com/intercreate/smpclient) without physical hardware, enabling integration tests in CI environments.

## Available Fixtures

### Serial Transport - Native Simulator

The `smp_server.fixture.serial.native_sim` fixture provides a Zephyr SMP server that runs natively on Linux and creates a pseudo-terminal (PTY) device for serial communication.

#### Building the Fixture

```bash
west build -b native_sim apps/smp-server -T smp_server.fixture.serial.native_sim
```

#### Running and Testing the Fixture

1. Run the fixture executable:
   ```bash
   ./build/smp-server/zephyr/zephyr.exe
   ```

2. The output will show the PTY device path:
   ```
   uart connected to pseudotty: /dev/pts/4
   *** Booting Zephyr OS build v4.2.0-6166-g8a72d776c5af ***
   [00:00:00.000,000] <inf> smp_sample: build time: Oct 19 2025 14:03:46
   ```

3. In another terminal, connect using smpmgr or smpclient:
   ```bash
   # Example using smpmgr (replace /dev/pts/4 with your actual PTY path)
   smpmgr --port /dev/pts/4 os echo hello
   ```

4. Stop the fixture with `Ctrl+C`

#### Notes

- The PTY device path (`/dev/pts/X`) will change each time you run the fixture
- This fixture is build-only in CI and is intended for local testing or integration tests in client tool repositories
- MCUboot is disabled (`CONFIG_IMG_MANAGER=n`, `SB_CONFIG_BOOTLOADER_NONE=y`) for simplicity
