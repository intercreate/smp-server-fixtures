"""Behavioural contract for collect_fixtures.

Run with ``uvx pytest`` (or ``uv run --with pytest pytest``) from this dir.
"""

import json
from pathlib import Path

import pytest

import collect_fixtures as cf


def kconfig(*lines: str) -> cf.Kconfig:
    return cf.Kconfig.parse("\n".join(lines))


def make_outputs(
    *,
    has_exe: bool = False,
    merged_hexes: tuple[str, ...] = (),
    has_hex: bool = False,
    has_elf: bool = False,
    has_mcuboot_hex: bool = False,
    has_mcuboot_elf: bool = False,
    has_signed: bool = False,
) -> cf.BuildOutputs:
    return cf.BuildOutputs(
        has_exe=has_exe,
        merged_hexes=merged_hexes,
        has_hex=has_hex,
        has_elf=has_elf,
        has_mcuboot_hex=has_mcuboot_hex,
        has_mcuboot_elf=has_mcuboot_elf,
        has_signed=has_signed,
    )


def make_build_dir(root: Path, name: str, *, files: dict[str, str]) -> Path:
    build_dir = root / name
    for rel, content in files.items():
        target = build_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return build_dir


def test_parse_scenario_dirname_ok() -> None:
    assert cf.parse_scenario_dirname("smp_server.fixture.serial.native_sim") == (
        "serial",
        "native_sim",
    )
    assert cf.parse_scenario_dirname("smp_server.fixture.serial_buf256.qemu_cortex_m0") == (
        "serial_buf256",
        "qemu_cortex_m0",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "smp_server.fixture.serial",  # no target
        "smp_server.fixture.a.b.c",  # more than one dot
        "something_else.serial.native_sim",  # wrong prefix
    ],
)
def test_parse_scenario_dirname_rejects(bad: str) -> None:
    with pytest.raises(cf.CollectError):
        cf.parse_scenario_dirname(bad)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("CONFIG_MCUMGR_TRANSPORT_BT", "bt"),
        ("CONFIG_UART_MCUMGR_RAW_PROTOCOL", "serial_raw"),
        ("CONFIG_MCUMGR_TRANSPORT_SHELL", "shell"),
        ("CONFIG_MCUMGR_TRANSPORT_UART", "serial"),
        ("CONFIG_MCUMGR_TRANSPORT_UDP", "udp"),
    ],
)
def test_classify_transport(key: str, expected: str) -> None:
    assert cf.classify_transport(kconfig(f"{key}=y")) == expected


def test_classify_transport_precedence() -> None:
    cfg = kconfig("CONFIG_MCUMGR_TRANSPORT_BT=y", "CONFIG_MCUMGR_TRANSPORT_UART=y")
    assert cf.classify_transport(cfg) == "bt"


def test_classify_transport_unknown() -> None:
    assert cf.classify_transport(kconfig("CONFIG_FOO=y")) == "unknown"


def test_ip_family() -> None:
    assert cf.ip_family(kconfig("CONFIG_MCUMGR_TRANSPORT_UART=y")) is None
    assert cf.ip_family(kconfig("CONFIG_MCUMGR_TRANSPORT_UDP=y")) == "ipv4"
    udp6 = kconfig("CONFIG_MCUMGR_TRANSPORT_UDP=y", "CONFIG_MCUMGR_TRANSPORT_UDP_IPV6=y")
    assert cf.ip_family(udp6) == "ipv6"


def test_enabled_groups_uses_fixed_order_not_config_order() -> None:
    cfg = kconfig(
        "CONFIG_MCUMGR_GRP_ENUM=y",
        "CONFIG_MCUMGR_GRP_OS=y",
        "CONFIG_MCUMGR_GRP_FS=y",
    )
    assert cf.enabled_groups(cfg) == ("os", "fs", "enum")


def test_enabled_groups_empty() -> None:
    assert cf.enabled_groups(kconfig("CONFIG_FOO=y")) == ()


def test_kconfig_get_int() -> None:
    cfg = kconfig("CONFIG_N=2048")
    assert cfg.get_int("CONFIG_N") == 2048
    assert cfg.get_int("CONFIG_MISSING") is None


def test_kconfig_get_int_rejects_non_int() -> None:
    with pytest.raises(cf.CollectError):
        kconfig("CONFIG_N=notanumber").get_int("CONFIG_N")


def test_kconfig_get_str_strips_quotes() -> None:
    assert kconfig('CONFIG_S="hello"').get_str("CONFIG_S") == "hello"


def test_select_artifact_rejects_exe_with_merged() -> None:
    # Host .exe + flashed-MCU merged image is a cross-target contradiction.
    with pytest.raises(cf.CollectError):
        cf.select_artifact(make_outputs(has_exe=True, merged_hexes=("merged_a.hex",)), "BASE")


def test_select_artifact_sysbuild_merged_with_companions() -> None:
    # Real sysbuild firmware: merged.hex alongside its zephyr.hex/.elf companions.
    art = cf.select_artifact(
        make_outputs(merged_hexes=("merged_a.hex",), has_hex=True, has_elf=True), "BASE"
    )
    assert isinstance(art, cf.MergedHex)
    assert art.name == "BASE.merged.hex"


def test_select_artifact_exe_beats_hex_and_elf() -> None:
    art = cf.select_artifact(make_outputs(has_exe=True, has_hex=True, has_elf=True), "BASE")
    assert isinstance(art, cf.Exe)


def test_select_artifact_hex_beats_elf() -> None:
    art = cf.select_artifact(make_outputs(has_hex=True, has_elf=True), "BASE")
    assert isinstance(art, cf.Hex)


def test_select_artifact_elf_only() -> None:
    assert isinstance(cf.select_artifact(make_outputs(has_elf=True), "BASE"), cf.Elf)


def test_select_artifact_mcuboot_hex_is_bootable() -> None:
    # Serial-recovery fixture: MCUboot's code-only hex is the bootable image.
    art = cf.select_artifact(make_outputs(has_mcuboot_hex=True, has_signed=True), "BASE")
    assert isinstance(art, cf.Hex)
    assert art.name == "BASE.hex"
    assert art.src == "mcuboot/zephyr/zephyr.hex"


def test_select_artifact_mcuboot_hex_beats_mcuboot_elf() -> None:
    art = cf.select_artifact(make_outputs(has_mcuboot_hex=True, has_mcuboot_elf=True), "BASE")
    assert isinstance(art, cf.Hex)
    assert art.src == "mcuboot/zephyr/zephyr.hex"


def test_select_artifact_mcuboot_elf_fallback() -> None:
    # Recovery build lacking the mcuboot hex falls back to MCUboot's own elf.
    art = cf.select_artifact(make_outputs(has_mcuboot_elf=True), "BASE")
    assert isinstance(art, cf.Elf)
    assert art.name == "BASE.elf"
    assert art.src == "mcuboot/zephyr/zephyr.elf"


def test_select_artifact_zephyr_elf_beats_mcuboot() -> None:
    art = cf.select_artifact(
        make_outputs(has_elf=True, has_mcuboot_hex=True, has_mcuboot_elf=True), "BASE"
    )
    assert isinstance(art, cf.Elf)
    assert art.src == "zephyr/zephyr.elf"


def test_select_artifact_none() -> None:
    assert cf.select_artifact(make_outputs(), "BASE") is None


def test_select_artifact_multiple_merged_raises() -> None:
    with pytest.raises(cf.CollectError):
        cf.select_artifact(make_outputs(merged_hexes=("merged_a.hex", "merged_b.hex")), "BASE")


def test_run_command_only_for_exe() -> None:
    assert cf.run_command(cf.Exe("n.exe", "zephyr/zephyr.exe")) == "./n.exe"
    assert cf.run_command(cf.MergedHex("n.merged.hex", "merged_a.hex")) is None
    assert cf.run_command(cf.Hex("n.hex", "zephyr/zephyr.hex")) is None
    assert cf.run_command(cf.Elf("n.elf", "zephyr/zephyr.elf")) is None


def test_qemu_command_exact_for_merged_hex() -> None:
    cmd = cf.qemu_command("qemu_cortex_m0", cf.MergedHex("ZZZ.merged.hex", "merged_a.hex"), None)
    assert cmd == (
        "qemu-system-arm -cpu cortex-m0 -machine microbit -nographic "
        "-chardev socket,id=con,host=127.0.0.1,port=<PORT>,server=on,wait=off "
        "-serial chardev:con -monitor none -device loader,file=ZZZ.merged.hex"
    )


def test_qemu_command_elf_uses_kernel() -> None:
    cmd = cf.qemu_command("mps2_an385", cf.Elf("ZZZ.elf", "zephyr/zephyr.elf"), None)
    assert cmd is not None
    assert "-cpu cortex-m3 -machine mps2-an385" in cmd
    assert cmd.endswith("-kernel ZZZ.elf")


def test_qemu_command_none_for_non_emulated() -> None:
    assert cf.qemu_command("native_sim", cf.Exe("n.exe", "zephyr/zephyr.exe"), None) is None


def test_qemu_command_two_loader_serial_recovery() -> None:
    cmd = cf.qemu_command(
        "mps2_an385",
        cf.Hex("BOOT.hex", "mcuboot/zephyr/zephyr.hex"),
        cf.SecondLoader(file="APP.signed.bin", addr="0x20050000"),
    )
    assert cmd == (
        "qemu-system-arm -cpu cortex-m3 -machine mps2-an385 -nographic "
        "-chardev socket,id=con,host=127.0.0.1,port=<PORT>,server=on,wait=off "
        "-serial chardev:con -serial null -monitor none "
        "-device loader,file=BOOT.hex "
        "-device loader,file=APP.signed.bin,addr=0x20050000"
    )
    assert cmd.count("-device loader") == 2


def test_second_loader_only_for_serial_recovery_hex_with_signed() -> None:
    boot_hex = cf.Hex("BASE.hex", "mcuboot/zephyr/zephyr.hex")
    boot_elf = cf.Elf("BASE.elf", "mcuboot/zephyr/zephyr.elf")
    assert cf.second_loader("serial_recovery", "BASE", boot_hex, True) == cf.SecondLoader(
        file="BASE.signed.bin", addr="0x20050000"
    )
    assert cf.second_loader("serial_recovery", "BASE", boot_hex, False) is None
    assert cf.second_loader("serial", "BASE", boot_hex, True) is None
    # The .elf fallback never carries a second loader (ROM regions would overlap).
    assert cf.second_loader("serial_recovery", "BASE", boot_elf, True) is None


def test_canonical_basename() -> None:
    assert (
        cf.canonical_basename("4.4.0", "05e7c6bddead", "native_sim", "serial")
        == "zephyr_4.4.0_smp_server_05e7c6bd_native_sim_serial"
    )


def test_manifest_json_sorted_and_valid() -> None:
    def entry(target: str, config: str) -> cf.ManifestEntry:
        return cf.ManifestEntry(
            artifact=f"{target}_{config}",
            target=target,
            config=config,
            transport="serial",
            ip_family=None,
            buf_size=None,
            buf_count=None,
            line_length_max=None,
            udp_port=None,
            groups=(),
            mcuboot=False,
            serial_recovery=False,
            run=None,
            qemu_cmd=None,
        )

    text = cf.manifest_json(
        [entry("native_sim", "udp"), entry("native_sim", "serial"), entry("mps2_an385", "shell")]
    )
    data: list[dict[str, object]] = json.loads(text)
    assert [(e["target"], e["config"]) for e in data] == [
        ("mps2_an385", "shell"),
        ("native_sim", "serial"),
        ("native_sim", "udp"),
    ]
    assert text.endswith("\n")
    assert list(data[0].keys()) == sorted(data[0].keys())


def test_process_native_sim_exe(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    build_dir = make_build_dir(
        tmp_path,
        "smp_server.fixture.serial.native_sim",
        files={
            "zephyr/zephyr.exe": "x",
            "zephyr/zephyr.elf": "x",
            "zephyr/.config": "CONFIG_MCUMGR_TRANSPORT_UART=y\nCONFIG_MCUMGR_GRP_OS=y\n",
        },
    )
    entry = cf.process_build_dir(build_dir, "4.4.0", "05e7c6bddead", out)
    assert entry is not None
    assert entry.artifact == "zephyr_4.4.0_smp_server_05e7c6bd_native_sim_serial.exe"
    assert entry.run == "./zephyr_4.4.0_smp_server_05e7c6bd_native_sim_serial.exe"
    assert entry.transport == "serial"
    assert entry.groups == ("os",)
    assert entry.qemu_cmd is None
    assert entry.mcuboot is False
    assert (out / entry.artifact).is_file()


def test_process_mps2_elf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    build_dir = make_build_dir(
        tmp_path,
        "smp_server.fixture.shell.mps2_an385",
        files={
            "zephyr/zephyr.elf": "x",
            "zephyr/.config": "CONFIG_MCUMGR_TRANSPORT_SHELL=y\nCONFIG_MCUMGR_TRANSPORT_UART=y\n",
        },
    )
    entry = cf.process_build_dir(build_dir, "4.4.0", "05e7c6bddead", out)
    assert entry is not None
    assert entry.artifact.endswith("_mps2_an385_shell.elf")
    assert entry.transport == "shell"
    assert entry.run is None
    assert entry.qemu_cmd is not None
    assert "-kernel " in entry.qemu_cmd


def test_process_serial_recovery_mps2_two_loader(tmp_path: Path) -> None:
    # Do-it-all mps2 serial recovery: MCUboot's code-only hex is the bootable
    # image and the signed app is pre-loaded into slot0's mock_flash so the
    # board boots straight to the app -- a two-loader QEMU command.
    out = tmp_path / "out"
    out.mkdir()
    build_dir = make_build_dir(
        tmp_path,
        "smp_server.fixture.serial_recovery.mps2_an385",
        files={
            "mcuboot/zephyr/zephyr.hex": "x",
            "smp-server/zephyr/.config": (
                "CONFIG_MCUMGR_TRANSPORT_UART=y\nCONFIG_MCUMGR_GRP_IMG=y\n"
            ),
            "smp-server/zephyr/zephyr.signed.bin": "x",
        },
    )
    entry = cf.process_build_dir(build_dir, "4.4.0", "05e7c6bddead", out)
    assert entry is not None
    base = "zephyr_4.4.0_smp_server_05e7c6bd_mps2_an385_serial_recovery"
    assert entry.artifact == f"{base}.hex"
    assert entry.serial_recovery is True
    assert entry.mcuboot is True
    assert entry.transport == "serial"
    assert entry.run is None

    cmd = entry.qemu_cmd
    assert cmd is not None
    assert "-cpu cortex-m3 -machine mps2-an385" in cmd
    assert "-serial chardev:con -serial null -monitor none" in cmd
    assert cmd.count("-device loader") == 2
    assert f"-device loader,file={base}.hex" in cmd
    assert f"-device loader,file={base}.signed.bin,addr=0x20050000" in cmd

    # Both loaders' files are shipped: the bootable mcuboot hex and the app payload.
    assert (out / f"{base}.hex").is_file()
    assert (out / f"{base}.signed.bin").is_file()


def test_process_serial_recovery_mps2_elf_fallback(tmp_path: Path) -> None:
    # A recovery build without the mcuboot hex still ships MCUboot's elf as a
    # single-loader -kernel image (the .signed.bin remains the upload payload).
    out = tmp_path / "out"
    out.mkdir()
    build_dir = make_build_dir(
        tmp_path,
        "smp_server.fixture.serial_recovery.mps2_an385",
        files={
            "mcuboot/zephyr/zephyr.elf": "x",
            "smp-server/zephyr/.config": (
                "CONFIG_MCUMGR_TRANSPORT_UART=y\nCONFIG_MCUMGR_GRP_IMG=y\n"
            ),
            "smp-server/zephyr/zephyr.signed.bin": "x",
        },
    )
    entry = cf.process_build_dir(build_dir, "4.4.0", "05e7c6bddead", out)
    assert entry is not None
    assert entry.artifact == "zephyr_4.4.0_smp_server_05e7c6bd_mps2_an385_serial_recovery.elf"
    assert entry.serial_recovery is True
    assert entry.mcuboot is True
    assert entry.qemu_cmd is not None
    assert entry.qemu_cmd.endswith("-kernel " + entry.artifact)
    assert entry.qemu_cmd.count("-device loader") == 0
    assert (out / entry.artifact).is_file()


def test_process_skips_image_less_stub(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    build_dir = make_build_dir(
        tmp_path, "smp_server.fixture.broken.native_sim", files={"build.log": "filtered"}
    )
    assert cf.process_build_dir(build_dir, "4.4.0", "05e7c6bddead", out) is None
    assert list(out.iterdir()) == []


def test_main_end_to_end(tmp_path: Path) -> None:
    twister_out = tmp_path / "twister-out"
    make_build_dir(
        twister_out,
        "smp_server.fixture.serial.native_sim",
        files={
            "zephyr/zephyr.exe": "x",
            "zephyr/.config": "CONFIG_MCUMGR_TRANSPORT_UART=y\n",
        },
    )
    make_build_dir(
        twister_out,
        "smp_server.fixture.serial.qemu_cortex_m0",
        files={
            "merged_smp_server.hex": "x",
            "smp-server/zephyr/.config": (
                "CONFIG_MCUMGR_TRANSPORT_UART=y\nCONFIG_MCUMGR_GRP_IMG=y\n"
            ),
            "smp-server/zephyr/zephyr.signed.bin": "x",
        },
    )
    make_build_dir(twister_out, "smp_server.fixture.broken.native_sim", files={"build.log": "x"})
    out = tmp_path / "out"
    rc = cf.main(
        [
            "--git-sha",
            "05e7c6bddead0000",
            "--zephyr-version",
            "4.4.0",
            "--leg",
            "ci",
            "--twister-out",
            str(twister_out),
            "--out-dir",
            str(out),
        ]
    )
    assert rc == 0
    manifest: list[dict[str, object]] = json.loads((out / "manifest-ci.json").read_text())
    assert len(manifest) == 2  # the image-less stub is skipped
    targets = [str(e["target"]) for e in manifest]
    assert targets == sorted(targets)
    assert any(p.name.endswith(".signed.bin") for p in out.iterdir())

    qemu = next(e for e in manifest if e["target"] == "qemu_cortex_m0")
    assert qemu["mcuboot"] is True
    assert "-device loader,file=" in str(qemu["qemu_cmd"])
    groups = qemu["groups"]
    assert isinstance(groups, list)
    assert "img" in groups

    nsim = next(e for e in manifest if e["target"] == "native_sim")
    assert str(nsim["run"]).startswith("./")
    assert nsim["mcuboot"] is False
