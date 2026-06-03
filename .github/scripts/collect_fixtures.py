# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Collect Twister build outputs into canonically-named fixtures + a manifest.

Replaces the inline bash that used to live in ``.github/workflows/build.yaml``.
The naming scheme is::

    zephyr_<zephyr-version>_smp_server_<8-char-sha>_<target>_<config>.<ext>

A functional core (parsing, classification, naming, manifest shaping) is kept
pure; a thin imperative shell does the directory listing, file copies, and the
manifest write. ``test_collect_fixtures.py`` is the behavioural contract.
"""

import argparse
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal, NamedTuple, Self, assert_never

FIXTURE_PREFIX: Final = "smp_server.fixture."
SIGNED_REL: Final = "smp-server/zephyr/zephyr.signed.bin"
MCUBOOT_HEX_REL: Final = "mcuboot/zephyr/zephyr.hex"
MCUBOOT_ELF_REL: Final = "mcuboot/zephyr/zephyr.elf"
SERIAL_RECOVERY_CONFIG: Final = "serial_recovery"
# slot0 mock_flash physical SRAM address for the mps2/an385 serial_recovery map:
# FlashSim @ 0x20040000 + slot0 flash offset 0x10000.
SLOT0_MOCK_FLASH_ADDR: Final = "0x20050000"


class CollectError(Exception):
    """A build output or Kconfig value the collector cannot interpret."""


type Transport = Literal["bt", "serial_raw", "shell", "serial", "udp", "unknown"]
type IpFamily = Literal["ipv4", "ipv6"]
type Group = Literal["os", "img", "stat", "settings", "fs", "shell", "enum", "zbasic"]


class Exe(NamedTuple):
    name: str
    src: str


class MergedHex(NamedTuple):
    name: str
    src: str


class Hex(NamedTuple):
    name: str
    src: str


class Elf(NamedTuple):
    name: str
    src: str


type Artifact = Exe | MergedHex | Hex | Elf


class Kconfig(NamedTuple):
    """A parsed Zephyr ``.config``."""

    values: Mapping[str, str]

    @classmethod
    def parse(cls, text: str) -> Self:
        pairs = (
            line.split("=", 1)
            for line in text.splitlines()
            if not line.startswith("#") and "=" in line
        )
        return cls({key: value for key, value in pairs})

    def is_set(self, key: str) -> bool:
        return self.values.get(key) == "y"

    def get_str(self, key: str) -> str | None:
        raw = self.values.get(key)
        return raw.strip('"') if raw is not None else None

    def get_int(self, key: str) -> int | None:
        raw = self.get_str(key)
        if raw is None:
            return None
        if not raw.isdigit():
            raise CollectError(f"{key}={raw!r} is not an integer")
        return int(raw)


class BuildOutputs(NamedTuple):
    """The image files present in a Twister build dir, gathered by the shell."""

    has_exe: bool
    merged_hexes: tuple[str, ...]
    has_hex: bool
    has_elf: bool
    has_mcuboot_hex: bool
    has_mcuboot_elf: bool
    has_signed: bool


class QemuMachine(NamedTuple):
    cpu: str
    machine: str


class ManifestEntry(NamedTuple):
    artifact: str
    target: str
    config: str
    transport: Transport
    ip_family: IpFamily | None
    buf_size: int | None
    buf_count: int | None
    line_length_max: int | None
    udp_port: int | None
    groups: tuple[Group, ...]
    mcuboot: bool
    serial_recovery: bool
    run: str | None
    qemu_cmd: str | None


TRANSPORT_LADDER: Final[tuple[tuple[str, Transport], ...]] = (
    ("CONFIG_MCUMGR_TRANSPORT_BT", "bt"),
    ("CONFIG_UART_MCUMGR_RAW_PROTOCOL", "serial_raw"),
    ("CONFIG_MCUMGR_TRANSPORT_SHELL", "shell"),
    ("CONFIG_MCUMGR_TRANSPORT_UART", "serial"),
    ("CONFIG_MCUMGR_TRANSPORT_UDP", "udp"),
)

GROUP_CONFIGS: Final[tuple[tuple[str, Group], ...]] = (
    ("CONFIG_MCUMGR_GRP_OS", "os"),
    ("CONFIG_MCUMGR_GRP_IMG", "img"),
    ("CONFIG_MCUMGR_GRP_STAT", "stat"),
    ("CONFIG_MCUMGR_GRP_SETTINGS", "settings"),
    ("CONFIG_MCUMGR_GRP_FS", "fs"),
    ("CONFIG_MCUMGR_GRP_SHELL", "shell"),
    ("CONFIG_MCUMGR_GRP_ENUM", "enum"),
    ("CONFIG_MCUMGR_GRP_ZBASIC", "zbasic"),
)

QEMU_MACHINES: Final[Mapping[str, QemuMachine]] = {
    "qemu_cortex_m0": QemuMachine(cpu="cortex-m0", machine="microbit"),
    "mps2_an385": QemuMachine(cpu="cortex-m3", machine="mps2-an385"),
}


def parse_scenario_dirname(dirname: str) -> tuple[str, str]:
    """Split a Twister build-dir name into ``(config, target)``.

    >>> parse_scenario_dirname("smp_server.fixture.serial_buf256.qemu_cortex_m0")
    ('serial_buf256', 'qemu_cortex_m0')
    """
    if not dirname.startswith(FIXTURE_PREFIX):
        raise CollectError(f"unexpected build dir name: {dirname!r}")
    rest = dirname.removeprefix(FIXTURE_PREFIX)
    config, sep, target = rest.partition(".")
    if not sep or "." in target:
        raise CollectError(f"expected '<config>.<target>' with a single dot, got {rest!r}")
    return config, target


def short_sha(git_sha: str) -> str:
    """Return the 8-char short SHA used in fixture names.

    >>> short_sha("05e7c6bddfe1626b1b10f3127c4714d678820914")
    '05e7c6bd'
    """
    return git_sha[:8]


def canonical_basename(zephyr_version: str, git_sha: str, target: str, config: str) -> str:
    """Canonical fixture stem, without directory or extension.

    >>> canonical_basename("4.4.0", "05e7c6bddfe1", "native_sim", "serial")
    'zephyr_4.4.0_smp_server_05e7c6bd_native_sim_serial'
    """
    return f"zephyr_{zephyr_version}_smp_server_{short_sha(git_sha)}_{target}_{config}"


def select_artifact(outputs: BuildOutputs, base: str) -> Artifact | None:
    """Choose the one primary image for a build dir (``None`` => skip the dir).

    A merged MCUboot image and a native_sim ``.exe`` come from different target
    classes (a flashed MCU vs the host) and never coexist, so treat the
    combination as a contradiction rather than silently preferring one. Real
    sysbuild dirs do legitimately carry ``merged.hex`` alongside ``zephyr.hex``
    and ``zephyr.elf``, so those fall through to the priority
    ``merged.hex > exe > hex > elf > mcuboot/zephyr/zephyr.hex >
    mcuboot/zephyr/zephyr.elf``. The last two are the serial-recovery fixture,
    where MCUboot itself is the bootable image and the app ships only as a
    ``.signed.bin`` second-loader payload. The code-only hex is preferred over
    the elf: its NOLOAD ``mock_flash`` region is absent from the hex, so a second
    QEMU loader can drop the signed app straight into slot0's backing store with
    no "ROM regions overlapping" error.
    """
    if outputs.has_exe and outputs.merged_hexes:
        raise CollectError(
            f"build dir has both a native_sim .exe and a merged image: {outputs.merged_hexes}"
        )
    if outputs.merged_hexes:
        if len(outputs.merged_hexes) > 1:
            raise CollectError(f"multiple merged_*.hex in build dir: {outputs.merged_hexes}")
        return MergedHex(name=f"{base}.merged.hex", src=outputs.merged_hexes[0])
    if outputs.has_exe:
        return Exe(name=f"{base}.exe", src="zephyr/zephyr.exe")
    if outputs.has_hex:
        return Hex(name=f"{base}.hex", src="zephyr/zephyr.hex")
    if outputs.has_elf:
        return Elf(name=f"{base}.elf", src="zephyr/zephyr.elf")
    if outputs.has_mcuboot_hex:
        return Hex(name=f"{base}.hex", src=MCUBOOT_HEX_REL)
    if outputs.has_mcuboot_elf:
        return Elf(name=f"{base}.elf", src=MCUBOOT_ELF_REL)
    return None


class SecondLoader(NamedTuple):
    """A ``-device loader,file=...,addr=...`` payload dropped after the kernel.

    The serial-recovery fixture boots MCUboot's code-only hex and pre-loads the
    signed app into slot0's ``mock_flash`` backing store, so no upload is needed.
    """

    file: str
    addr: str


def is_serial_recovery(config: str) -> bool:
    return config == SERIAL_RECOVERY_CONFIG


def is_mcuboot(config: str, artifact: Artifact) -> bool:
    return isinstance(artifact, MergedHex) or is_serial_recovery(config)


def second_loader(
    config: str, base: str, artifact: Artifact, has_signed: bool
) -> SecondLoader | None:
    """The serial-recovery app payload, or ``None`` for single-loader fixtures.

    Only the code-only MCUboot ``Hex`` can carry a second loader: its NOLOAD
    ``mock_flash`` region is absent from the hex, so the signed app drops into
    slot0's backing store with no ROM-region overlap. The ``Elf`` fallback boots
    as a plain ``-kernel`` image (the app is uploaded over SMP instead).

    >>> boot_hex = Hex("BASE.hex", MCUBOOT_HEX_REL)
    >>> boot_elf = Elf("BASE.elf", MCUBOOT_ELF_REL)
    >>> second_loader("serial_recovery", "BASE", boot_hex, True)
    SecondLoader(file='BASE.signed.bin', addr='0x20050000')
    >>> second_loader("serial", "BASE", boot_hex, True) is None
    True
    >>> second_loader("serial_recovery", "BASE", boot_elf, True) is None
    True
    >>> second_loader("serial_recovery", "BASE", boot_hex, False) is None
    True
    """
    if not (is_serial_recovery(config) and has_signed and isinstance(artifact, Hex)):
        return None
    return SecondLoader(file=f"{base}.signed.bin", addr=SLOT0_MOCK_FLASH_ADDR)


def run_command(artifact: Artifact) -> str | None:
    """The native_sim launch command; ``None`` for every non-executable image."""
    match artifact:
        case Exe(name):
            return f"./{name}"
        case MergedHex() | Hex() | Elf():
            return None
        case _:
            assert_never(artifact)


def qemu_load(artifact: Artifact) -> str:
    """The QEMU image-load flag, chosen by image kind (not filename suffix)."""
    match artifact:
        case Elf(name):
            return f"-kernel {name}"
        case Exe(name) | MergedHex(name) | Hex(name):
            return f"-device loader,file={name}"
        case _:
            assert_never(artifact)


def qemu_command(target: str, artifact: Artifact, payload: SecondLoader | None) -> str | None:
    """The QEMU launch command, single- or (serial-recovery) two-loader.

    With a ``payload`` the SMP socket keeps uart0 while uart1 (the log) is wired
    to ``null``, then MCUboot's code-only hex loads and the signed app is dropped
    into slot0's ``mock_flash`` backing store at ``payload.addr`` -- booting
    straight to the app with no upload.
    """
    machine = QEMU_MACHINES.get(target)
    if machine is None:
        return None
    serial = "-serial chardev:con" if payload is None else "-serial chardev:con -serial null"
    extra = "" if payload is None else f" -device loader,file={payload.file},addr={payload.addr}"
    return (
        f"qemu-system-arm -cpu {machine.cpu} -machine {machine.machine} -nographic "
        f"-chardev socket,id=con,host=127.0.0.1,port=<PORT>,server=on,wait=off "
        f"{serial} -monitor none {qemu_load(artifact)}{extra}"
    )


def classify_transport(cfg: Kconfig) -> Transport:
    return next(
        (transport for key, transport in TRANSPORT_LADDER if cfg.is_set(key)),
        "unknown",
    )


def ip_family(cfg: Kconfig) -> IpFamily | None:
    if not cfg.is_set("CONFIG_MCUMGR_TRANSPORT_UDP"):
        return None
    return "ipv6" if cfg.is_set("CONFIG_MCUMGR_TRANSPORT_UDP_IPV6") else "ipv4"


def enabled_groups(cfg: Kconfig) -> tuple[Group, ...]:
    return tuple(name for key, name in GROUP_CONFIGS if cfg.is_set(key))


def make_entry(
    config: str, target: str, base: str, artifact: Artifact, outputs: BuildOutputs, cfg: Kconfig
) -> ManifestEntry:
    return ManifestEntry(
        artifact=artifact.name,
        target=target,
        config=config,
        transport=classify_transport(cfg),
        ip_family=ip_family(cfg),
        buf_size=cfg.get_int("CONFIG_MCUMGR_TRANSPORT_NETBUF_SIZE"),
        buf_count=cfg.get_int("CONFIG_MCUMGR_TRANSPORT_NETBUF_COUNT"),
        line_length_max=cfg.get_int("CONFIG_UART_MCUMGR_RX_BUF_SIZE"),
        udp_port=cfg.get_int("CONFIG_MCUMGR_TRANSPORT_UDP_PORT"),
        groups=enabled_groups(cfg),
        mcuboot=is_mcuboot(config, artifact),
        serial_recovery=is_serial_recovery(config),
        run=run_command(artifact),
        qemu_cmd=qemu_command(
            target, artifact, second_loader(config, base, artifact, outputs.has_signed)
        ),
    )


def manifest_json(entries: Sequence[ManifestEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: (entry.target, entry.config))
    return json.dumps([entry._asdict() for entry in ordered], sort_keys=True, indent=2) + "\n"


def gather_outputs(build_dir: Path) -> BuildOutputs:
    return BuildOutputs(
        has_exe=(build_dir / "zephyr" / "zephyr.exe").is_file(),
        merged_hexes=tuple(sorted(path.name for path in build_dir.glob("merged_*.hex"))),
        has_hex=(build_dir / "zephyr" / "zephyr.hex").is_file(),
        has_elf=(build_dir / "zephyr" / "zephyr.elf").is_file(),
        has_mcuboot_hex=(build_dir / MCUBOOT_HEX_REL).is_file(),
        has_mcuboot_elf=(build_dir / MCUBOOT_ELF_REL).is_file(),
        has_signed=(build_dir / SIGNED_REL).is_file(),
    )


def read_kconfig(build_dir: Path) -> Kconfig:
    sysbuild = build_dir / "smp-server" / "zephyr" / ".config"
    cfg = sysbuild if sysbuild.is_file() else build_dir / "zephyr" / ".config"
    return Kconfig.parse(cfg.read_text()) if cfg.is_file() else Kconfig({})


def process_build_dir(
    build_dir: Path, zephyr_version: str, git_sha: str, out_dir: Path
) -> ManifestEntry | None:
    config, target = parse_scenario_dirname(build_dir.name)
    base = canonical_basename(zephyr_version, git_sha, target, config)
    outputs = gather_outputs(build_dir)
    artifact = select_artifact(outputs, base)
    if artifact is None:
        return None
    shutil.copy(build_dir / artifact.src, out_dir / artifact.name)
    if outputs.has_signed:
        shutil.copy(build_dir / SIGNED_REL, out_dir / f"{base}.signed.bin")
    return make_entry(config, target, base, artifact, outputs, read_kconfig(build_dir))


def discover_build_dirs(twister_out: Path) -> list[Path]:
    return sorted(path for path in twister_out.rglob(f"{FIXTURE_PREFIX}*") if path.is_dir())


class Args(NamedTuple):
    git_sha: str
    zephyr_version: str
    leg: str
    twister_out: Path
    out_dir: Path


def parse_args(argv: Sequence[str] | None) -> Args:
    parser = argparse.ArgumentParser(description="Collect Twister fixtures + manifest.")
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--zephyr-version", required=True)
    parser.add_argument("--leg", required=True)
    parser.add_argument("--twister-out", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    ns = parser.parse_args(argv)
    return Args(
        git_sha=ns.git_sha,
        zephyr_version=ns.zephyr_version,
        leg=ns.leg,
        twister_out=ns.twister_out,
        out_dir=ns.out_dir,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        entry
        for build_dir in discover_build_dirs(args.twister_out)
        if (entry := process_build_dir(build_dir, args.zephyr_version, args.git_sha, args.out_dir))
        is not None
    ]
    content = manifest_json(entries)
    (args.out_dir / f"manifest-{args.leg}.json").write_text(content)
    print(f"Collected {len(entries)} fixtures into {args.out_dir}/")
    for path in sorted(args.out_dir.iterdir()):
        print(f"  {path.name}")
    print(content)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CollectError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
