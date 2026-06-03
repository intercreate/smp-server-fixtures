"""Behavioural contract for validate_release.

Run with ``uvx pytest`` (or ``uv run --with pytest pytest``) from this dir.
"""

import json
from pathlib import Path

import pytest

import validate_release as vr

SHA = "2ad0d6bf"
VER = "4.4.0"


def asset(target: str, config: str, ext: str, sha: str = SHA) -> str:
    return f"zephyr_{VER}_smp_server_{sha}_{target}_{config}.{ext}"


def native_sim_entry(config: str, sha: str = SHA) -> vr.Entry:
    name = asset("native_sim", config, "exe", sha)
    return vr.Entry(artifact=name, run=f"./{name}", qemu_cmd=None)


def qemu_merged_entry(target: str, config: str, sha: str = SHA) -> vr.Entry:
    name = asset(target, config, "merged.hex", sha)
    return vr.Entry(artifact=name, run=None, qemu_cmd=f"qemu ... -device loader,file={name}")


def mps2_recovery_entry(config: str, sha: str = SHA) -> vr.Entry:
    boot = asset("mps2_an385", config, "hex", sha)
    payload = asset("mps2_an385", config, "signed.bin", sha)
    qemu = (
        f"qemu-system-arm -cpu cortex-m3 -machine mps2-an385 ... "
        f"-device loader,file={boot} -device loader,file={payload},addr=0x20050000"
    )
    return vr.Entry(artifact=boot, run=None, qemu_cmd=qemu)


def hardware_entry(config: str, sha: str = SHA) -> vr.Entry:
    # Build-only nrf image: shipped with a signed payload, no run/qemu_cmd.
    name = asset("nrf52840dk", config, "merged.hex", sha)
    return vr.Entry(artifact=name, run=None, qemu_cmd=None)


def files_for(entries: list[vr.Entry], *, extra_payloads: tuple[str, ...] = ()) -> list[str]:
    names = {e.artifact for e in entries}
    for e in entries:
        names |= set(vr.referenced_files(e))
    return sorted(names | set(extra_payloads) | {"manifest.json", "SHA256SUMS"})


def test_is_asset() -> None:
    assert vr.is_asset(asset("native_sim", "serial", "exe")) is True
    assert vr.is_asset("SHA256SUMS") is False
    assert vr.is_asset("manifest.json") is False


def test_asset_sha_and_payload_share_stem() -> None:
    img = asset("mps2_an385", "serial_recovery", "hex")
    payload = asset("mps2_an385", "serial_recovery", "signed.bin")
    assert vr.asset_sha(img) == SHA
    assert vr.fixture_stem(img) == vr.fixture_stem(payload)
    assert vr.is_payload(payload) is True
    assert vr.is_payload(img) is False


def test_fixture_stem_survives_version_dots() -> None:
    # The Zephyr version carries dots that precede the SHA marker.
    name = "zephyr_4.4.0_smp_server_2ad0d6bf_qemu_cortex_m0_serial.merged.hex"
    assert vr.fixture_stem(name) == "zephyr_4.4.0_smp_server_2ad0d6bf_qemu_cortex_m0_serial"


def test_referenced_files_two_loader() -> None:
    entry = mps2_recovery_entry("serial_recovery")
    refs = vr.referenced_files(entry)
    assert entry.artifact in refs
    assert any(r.endswith(".signed.bin") for r in refs)
    assert len(refs) == 2


def test_parse_entries_ok() -> None:
    data = [
        {"artifact": "a.exe", "run": "./a.exe", "qemu_cmd": None, "target": "native_sim"},
        {"artifact": "b.hex", "run": None, "qemu_cmd": "qemu -kernel b.hex"},
    ]
    entries = vr.parse_entries(data)
    assert [e.artifact for e in entries] == ["a.exe", "b.hex"]
    assert entries[0].run == "./a.exe"


@pytest.mark.parametrize(
    "bad",
    [
        {"not": "a list"},
        [{"no": "artifact"}],
        [{"artifact": 123}],
        [{"artifact": "a.exe", "run": 5}],
    ],
)
def test_parse_entries_rejects(bad: object) -> None:
    with pytest.raises(vr.ValidationError):
        vr.parse_entries(bad)


def test_validate_accepts_sound_release() -> None:
    entries = [
        native_sim_entry("serial"),
        qemu_merged_entry("qemu_cortex_m0", "serial"),
        mps2_recovery_entry("serial_recovery"),
        hardware_entry("serial"),
    ]
    extra = (asset("nrf52840dk", "serial", "signed.bin"),)
    assert vr.validate(files_for(entries, extra_payloads=extra), entries, SHA) == []


def test_validate_flags_foreign_sha() -> None:
    # The exact issue #4 footgun: a release accumulating a second build's assets.
    entries = [native_sim_entry("serial")]
    stale = asset("native_sim", "udp", "exe", sha="cbc3cd94")
    problems = vr.validate([*files_for(entries), stale], entries, SHA)
    assert any("foreign-SHA" in p and "cbc3cd94" in p for p in problems)


def test_validate_flags_orphan_image() -> None:
    entries = [native_sim_entry("serial")]
    orphan = asset("native_sim", "udp", "exe")  # shipped, not in the manifest
    problems = vr.validate([*files_for(entries), orphan], entries, SHA)
    assert any("no manifest entry" in p and "udp" in p for p in problems)


def test_validate_flags_dangling_entry() -> None:
    entries = [native_sim_entry("serial"), qemu_merged_entry("qemu_cortex_m0", "serial")]
    # Ship only the first entry's file; the qemu artifact is missing.
    names = [native_sim_entry("serial").artifact, "manifest.json"]
    problems = vr.validate(names, entries, SHA)
    assert any("is not shipped" in p for p in problems)


def test_validate_flags_orphan_payload() -> None:
    entries = [native_sim_entry("serial")]
    payload = asset("mps2_an385", "serial_recovery", "signed.bin")  # belongs to nothing
    problems = vr.validate([*files_for(entries), payload], entries, SHA)
    assert any("payload" in p and "no matching manifest entry" in p for p in problems)


def test_validate_flags_stray_file() -> None:
    entries = [native_sim_entry("serial")]
    problems = vr.validate([*files_for(entries), "junk.txt"], entries, SHA)
    assert any("unexpected file" in p for p in problems)


def test_validate_flags_empty_manifest() -> None:
    assert "manifest has no entries" in vr.validate(["manifest.json"], [], SHA)


def test_validate_flags_duplicate_artifact() -> None:
    entries = [native_sim_entry("serial"), native_sim_entry("serial")]
    problems = vr.validate(files_for(entries), entries, SHA)
    assert any("duplicate" in p for p in problems)


def test_main_end_to_end_ok(tmp_path: Path) -> None:
    entries = [
        native_sim_entry("serial"),
        mps2_recovery_entry("serial_recovery"),
    ]
    extra = (asset("mps2_an385", "serial_recovery", "signed.bin"),)
    for name in files_for(entries, extra_payloads=extra):
        (tmp_path / name).write_text("x")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [{"artifact": e.artifact, "run": e.run, "qemu_cmd": e.qemu_cmd} for e in entries]
        )
    )
    rc = vr.main(
        ["--manifest", str(manifest), "--assets-dir", str(tmp_path), "--git-sha", SHA + "deadbeef"]
    )
    assert rc == 0


def test_main_end_to_end_detects_multi_sha(tmp_path: Path) -> None:
    entries = [native_sim_entry("serial")]
    for name in files_for(entries):
        (tmp_path / name).write_text("x")
    (tmp_path / asset("native_sim", "udp", "exe", sha="cbc3cd94")).write_text("x")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"artifact": entries[0].artifact, "run": entries[0].run}]))
    rc = vr.main(["--manifest", str(manifest), "--assets-dir", str(tmp_path), "--git-sha", SHA])
    assert rc == 1
