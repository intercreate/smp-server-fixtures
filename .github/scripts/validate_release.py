# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Validate a merged release directory before it is published.

Guards the two failure modes from issue #4: a release whose assets accumulate
more than one build's SHA, and a release whose ``manifest.json`` and shipped
files disagree. Run in the release job after the per-leg manifests are merged
and every fixture file is gathered into one directory::

    uv run validate_release.py --manifest manifest.json --assets-dir . \\
        --git-sha "$GITHUB_SHA"

The invariants, all keyed off this build's short SHA:

* **Provenance** -- every shipped ``zephyr_*`` asset carries *this* build's SHA,
  so a release can never silently accumulate assets from older builds.
* **No orphan images** -- every primary image (a ``zephyr_*`` asset that is not a
  ``.signed.bin`` payload) is named by exactly one manifest entry, so the
  manifest fully describes the release and every emulatable asset is launchable.
* **No dangling entries** -- every entry's ``artifact`` and every file named in a
  ``run`` / ``qemu_cmd`` exists in the directory.
* **Payloads belong to a fixture** -- every ``.signed.bin`` shares a fixture stem
  with some entry's ``artifact``.

A pure core (name parsing + the bijection checks) returns a list of
human-readable problems; a thin shell lists the directory, loads the manifest,
and exits non-zero if the core found any. ``test_validate_release.py`` is the
behavioural contract.
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, NamedTuple

ASSET_PREFIX: Final = "zephyr_"
SMP_MARKER: Final = "_smp_server_"
SIGNED_SUFFIX: Final = ".signed.bin"
# Files a release legitimately carries that are not per-fixture assets.
NON_ASSET_FILES: Final = frozenset({"manifest.json", "SHA256SUMS"})
# `-device loader,file=X[,addr=Y]` and `-kernel X` each name a shipped asset.
_LOADER_FILE: Final = re.compile(r"file=([^\s,]+)")
_KERNEL_FILE: Final = re.compile(r"-kernel\s+(\S+)")


class ValidationError(Exception):
    """A manifest the validator cannot interpret (malformed, not a list, ...)."""


class Entry(NamedTuple):
    """The launch-relevant fields of one ``manifest.json`` entry."""

    artifact: str
    run: str | None
    qemu_cmd: str | None


def short_sha(git_sha: str) -> str:
    """The 8-char short SHA used in asset names.

    >>> short_sha("2ad0d6bfdeadbeef")
    '2ad0d6bf'
    """
    return git_sha[:8]


def is_asset(name: str) -> bool:
    """Whether a filename is a canonical per-fixture asset.

    >>> is_asset("zephyr_4.4.0_smp_server_2ad0d6bf_native_sim_serial.exe")
    True
    >>> is_asset("SHA256SUMS")
    False
    """
    return name.startswith(ASSET_PREFIX) and SMP_MARKER in name


def asset_sha(name: str) -> str:
    """The SHA field of a canonical asset name.

    >>> asset_sha("zephyr_4.4.0_smp_server_2ad0d6bf_native_sim_serial.exe")
    '2ad0d6bf'
    >>> asset_sha("zephyr_4.4.0_smp_server_9ccdd4d2_mps2_an385_serial_recovery.signed.bin")
    '9ccdd4d2'
    """
    return name.split(SMP_MARKER, 1)[1].split("_", 1)[0]


def is_payload(name: str) -> bool:
    """Whether an asset is an upload payload rather than a primary image.

    >>> is_payload("zephyr_4.4.0_smp_server_2ad0d6bf_nrf52840dk_serial.signed.bin")
    True
    >>> is_payload("zephyr_4.4.0_smp_server_2ad0d6bf_qemu_cortex_m0_serial.merged.hex")
    False
    """
    return name.endswith(SIGNED_SUFFIX)


def fixture_stem(name: str) -> str:
    """A canonical asset's name with its file extension removed.

    Robust to the dots in the Zephyr version (which precede the SHA marker), so a
    payload and the image it belongs to share a stem.

    >>> fixture_stem("zephyr_4.4.0_smp_server_2ad0d6bf_qemu_cortex_m0_serial.merged.hex")
    'zephyr_4.4.0_smp_server_2ad0d6bf_qemu_cortex_m0_serial'
    >>> fixture_stem("zephyr_4.4.0_smp_server_2ad0d6bf_native_sim_serial.exe")
    'zephyr_4.4.0_smp_server_2ad0d6bf_native_sim_serial'
    >>> fixture_stem("zephyr_4.4.0_smp_server_2ad0d6bf_nrf52840dk_serial.signed.bin")
    'zephyr_4.4.0_smp_server_2ad0d6bf_nrf52840dk_serial'
    """
    head, marker, rest = name.partition(SMP_MARKER)
    return head + marker + rest.split(".", 1)[0]


def referenced_files(entry: Entry) -> frozenset[str]:
    """Asset filenames a fixture's launch commands point at.

    >>> e = Entry("a.hex", None, "qemu ... -device loader,file=a.hex "
    ...           "-device loader,file=b.signed.bin,addr=0x20050000")
    >>> sorted(referenced_files(e))
    ['a.hex', 'b.signed.bin']
    >>> sorted(referenced_files(Entry("n.exe", "./n.exe", None)))
    ['n.exe']
    >>> sorted(referenced_files(Entry("k.elf", None, "qemu ... -kernel k.elf")))
    ['k.elf']
    """
    files: set[str] = set()
    if entry.run is not None:
        files.add(entry.run.removeprefix("./"))
    if entry.qemu_cmd is not None:
        files.update(_LOADER_FILE.findall(entry.qemu_cmd))
        files.update(_KERNEL_FILE.findall(entry.qemu_cmd))
    return frozenset(files)


def parse_entries(data: object) -> list[Entry]:
    """Project a decoded ``manifest.json`` onto the launch-relevant fields."""
    if not isinstance(data, list):
        raise ValidationError("manifest is not a JSON array")
    entries: list[Entry] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise ValidationError(f"manifest entry is not an object: {item!r}")
        artifact = item.get("artifact")
        if not isinstance(artifact, str):
            raise ValidationError(f"manifest entry has no string 'artifact': {item!r}")
        run = item.get("run")
        qemu_cmd = item.get("qemu_cmd")
        if run is not None and not isinstance(run, str):
            raise ValidationError(f"{artifact}: 'run' is not a string or null")
        if qemu_cmd is not None and not isinstance(qemu_cmd, str):
            raise ValidationError(f"{artifact}: 'qemu_cmd' is not a string or null")
        entries.append(Entry(artifact=artifact, run=run, qemu_cmd=qemu_cmd))
    return entries


def check_provenance(asset_names: Sequence[str], short: str) -> list[str]:
    """Every shipped asset carries this build's SHA (no multi-SHA accumulation).

    >>> check_provenance(["zephyr_4.4.0_smp_server_2ad0d6bf_native_sim_serial.exe"], "2ad0d6bf")
    []
    >>> only = check_provenance(["zephyr_4.4.0_smp_server_cbc3cd94_native_sim_udp.exe"], "2ad0d6bf")
    >>> only[0].startswith("foreign-SHA asset (build is 2ad0d6bf):") and "cbc3cd94" in only[0]
    True
    """
    return [
        f"foreign-SHA asset (build is {short}): {name!r} carries {asset_sha(name)!r}"
        for name in asset_names
        if is_asset(name) and asset_sha(name) != short
    ]


def check_no_orphan_images(asset_names: Sequence[str], artifacts: frozenset[str]) -> list[str]:
    """Every primary image asset is named by a manifest entry."""
    return [
        f"image {name!r} is shipped but has no manifest entry"
        for name in asset_names
        if is_asset(name) and not is_payload(name) and name not in artifacts
    ]


def check_entries_have_files(entries: Sequence[Entry], asset_names: frozenset[str]) -> list[str]:
    """Every entry's artifact and every launch-command file is shipped."""
    problems: list[str] = []
    for entry in entries:
        if entry.artifact not in asset_names:
            problems.append(f"manifest entry artifact {entry.artifact!r} is not shipped")
        problems.extend(
            f"{entry.artifact}: launch command names missing file {ref!r}"
            for ref in sorted(referenced_files(entry))
            if ref not in asset_names
        )
    return problems


def check_payloads_belong(asset_names: Sequence[str], entries: Sequence[Entry]) -> list[str]:
    """Every ``.signed.bin`` payload shares a fixture stem with some entry."""
    entry_stems = frozenset(fixture_stem(entry.artifact) for entry in entries)
    return [
        f"payload {name!r} has no matching manifest entry"
        for name in asset_names
        if is_asset(name) and is_payload(name) and fixture_stem(name) not in entry_stems
    ]


def check_no_stray_files(asset_names: Sequence[str]) -> list[str]:
    """Nothing in the release is unaccounted for (not an asset, not the manifest)."""
    return [
        f"unexpected file in release: {name!r}"
        for name in asset_names
        if not is_asset(name) and name not in NON_ASSET_FILES
    ]


def check_unique_artifacts(entries: Sequence[Entry]) -> list[str]:
    """No two manifest entries claim the same artifact."""
    seen: set[str] = set()
    dups: list[str] = []
    for entry in entries:
        if entry.artifact in seen:
            dups.append(f"duplicate manifest artifact: {entry.artifact!r}")
        seen.add(entry.artifact)
    return dups


def validate(asset_names: Sequence[str], entries: Sequence[Entry], git_sha: str) -> list[str]:
    """All release problems, de-duplicated and sorted (empty => the release is sound)."""
    short = short_sha(git_sha)
    artifacts = frozenset(entry.artifact for entry in entries)
    names = frozenset(asset_names)
    problems = [
        *([] if entries else ["manifest has no entries"]),
        *check_provenance(asset_names, short),
        *check_no_orphan_images(asset_names, artifacts),
        *check_entries_have_files(entries, names),
        *check_payloads_belong(asset_names, entries),
        *check_no_stray_files(asset_names),
        *check_unique_artifacts(entries),
    ]
    return sorted(set(problems))


def list_assets(assets_dir: Path) -> list[str]:
    return sorted(path.name for path in assets_dir.iterdir() if path.is_file())


class Args(NamedTuple):
    manifest: Path
    assets_dir: Path
    git_sha: str


def parse_args(argv: Sequence[str] | None) -> Args:
    parser = argparse.ArgumentParser(description="Validate a merged release directory.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    ns = parser.parse_args(argv)
    return Args(manifest=ns.manifest, assets_dir=ns.assets_dir, git_sha=ns.git_sha)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    entries = parse_entries(json.loads(args.manifest.read_text()))
    asset_names = list_assets(args.assets_dir)
    problems = validate(asset_names, entries, args.git_sha)
    if problems:
        print(f"Release validation FAILED ({len(problems)} problem(s)):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(
        f"Release validation OK: {len(entries)} manifest entries, "
        f"{sum(is_asset(name) for name in asset_names)} assets, all SHA {short_sha(args.git_sha)}."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
