"""Strict, offline loader for `configs/benchmarks/*.yaml` (benchmark_config_version 1).

Default-deny at every level: duplicate YAML keys, unknown or missing keys, wrong types, unknown
enum values and a value without provenance are refused. Unknown facts are written as
`value: null` with `provenance: UNKNOWN`. Field-level rules (finite, positive, units, character
allow-lists, immutability, leakage between roles) live in the `provenance` constructors, which
this loader only calls. Nothing here opens a network connection or a data file; the benchmark
configs are separate from the transmit configs, so they cannot change an `experiment_id`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any, TypeVar

import yaml

from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    Checksum,
    ErrorCode,
    LicenseRecord,
    LicenseStatus,
    ParameterValue,
    Permission,
    Provenance,
    SourceRecord,
    Split,
    check_text,
)

CONFIG_VERSION = 1
_E = TypeVar("_E")

_SOURCE_KEYS = {"source_id", "kind", "title", "doi", "url", "version", "retrieved"}
_SOURCE_OPTIONAL = {"licenses", "assets", "parameters", "plan_sha256"}
_LICENSE_KEYS = {
    "scope",
    "status",
    "license_id",
    "private_research_use",
    "public_redistribution",
    "derivatives",
    "commercial_use",
    "note",
    "read_how",
}
_PARAMETER_KEYS = {"value", "provenance", "unit", "as_stated", "source_ref", "read_how"}
_ASSET_KEYS = {
    "filename",
    "asset_version",
    "size_bytes",
    "split",
    "group",
    "md5_supplied",
    "sample_rate_wording",
    "parameters",
}


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping key given twice (PyYAML keeps the last one silently)."""


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    loader.flatten_mapping(node)
    seen: set[Hashable] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, Hashable):
            raise yaml.constructor.ConstructorError(
                None, None, f"unhashable mapping key {key!r}", key_node.start_mark
            )
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def load_strict_yaml(text: str) -> Any:
    """Parse YAML with the strict loader: duplicate keys at any depth raise `yaml.YAMLError`."""
    return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass


def _mapping(
    value: Any, where: str, required: set[str], optional: frozenset[str] | set[str] = frozenset()
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchmarkError(f"{where}: must be a mapping, got {type(value).__name__}")
    missing = sorted(required - set(value))
    if missing:
        raise BenchmarkError(f"{where}: missing keys {missing}")
    unknown = sorted(set(value) - required - set(optional), key=str)
    if unknown:
        raise BenchmarkError(f"{where}: unknown keys {unknown}")
    return value


def _enum(kind: type[_E], value: Any, where: str) -> _E:
    try:
        return kind(value)  # type: ignore[call-arg]
    except ValueError:
        accepted = [m.value for m in kind]  # type: ignore[attr-defined]
        raise BenchmarkError(f"{where}: {value!r} is not one of {accepted}") from None


def _parameter(raw: Any, where: str) -> ParameterValue:
    body = _mapping(raw, where, {"value", "provenance"}, _PARAMETER_KEYS - {"value", "provenance"})
    return ParameterValue(
        value=body["value"],
        provenance=_enum(Provenance, body["provenance"], f"{where}.provenance"),
        unit=check_text(body.get("unit"), f"{where}.unit", nullable=True),
        as_stated=check_text(body.get("as_stated"), f"{where}.as_stated", nullable=True),
        source_ref=check_text(body.get("source_ref"), f"{where}.source_ref", nullable=True),
        read_how=check_text(body.get("read_how"), f"{where}.read_how", nullable=True),
    )


def _parameters(raw: Any, where: str) -> dict[str, ParameterValue]:
    if not isinstance(raw, Mapping):
        raise BenchmarkError(f"{where}: must be a mapping of parameter name to record")
    return {str(name): _parameter(body, f"{where}.{name}") for name, body in raw.items()}


def _license(raw: Any, where: str) -> LicenseRecord:
    body = _mapping(raw, where, _LICENSE_KEYS - {"note", "read_how"}, {"note", "read_how"})
    return LicenseRecord(
        scope=check_text(body["scope"], f"{where}.scope"),
        status=_enum(LicenseStatus, body["status"], f"{where}.status"),
        license_id=check_text(body["license_id"], f"{where}.license_id", nullable=True),
        private_research_use=_enum(Permission, body["private_research_use"], f"{where}.private"),
        public_redistribution=_enum(Permission, body["public_redistribution"], f"{where}.public"),
        derivatives=_enum(Permission, body["derivatives"], f"{where}.derivatives"),
        commercial_use=_enum(Permission, body["commercial_use"], f"{where}.commercial_use"),
        note=check_text(body.get("note", "n/a"), f"{where}.note"),
        read_how=check_text(body.get("read_how"), f"{where}.read_how", nullable=True),
    )


def _asset(raw: Any, source: Mapping[str, Any], where: str) -> AssetRecord:
    body = _mapping(
        raw,
        where,
        {"filename", "asset_version", "split", "group", "parameters"},
        _ASSET_KEYS - {"filename", "asset_version", "split", "group", "parameters"},
    )
    return AssetRecord(
        source_id=source["source_id"],
        doi=source["doi"],
        url=source["url"],
        asset_version=check_text(body["asset_version"], f"{where}.asset_version"),
        filename=check_text(body["filename"], f"{where}.filename"),
        checksum=Checksum(
            md5_supplied=check_text(
                body.get("md5_supplied"), f"{where}.md5_supplied", nullable=True
            )
        ),
        size_bytes=body.get("size_bytes"),
        split=_enum(Split, body["split"], f"{where}.split"),
        group=check_text(body["group"], f"{where}.group"),
        parameters=_parameters(body["parameters"], f"{where}.parameters"),
        sample_rate_wording=check_text(
            body.get("sample_rate_wording"), f"{where}.sample_rate_wording", nullable=True
        ),
    )


def parse_source(raw: Any) -> SourceRecord:
    """Validate a parsed `source` mapping and build the frozen record."""
    body = _mapping(raw, "source", _SOURCE_KEYS, _SOURCE_OPTIONAL)
    if "licenses" not in body or not isinstance(body["licenses"], list) or not body["licenses"]:
        raise BenchmarkError(
            "source.licenses: licence state is required (use status UNVERIFIED if unknown)",
            ErrorCode.LICENSE_UNVERIFIED,
        )
    assets_raw = body.get("assets", [])
    if not isinstance(assets_raw, list):
        raise BenchmarkError("source.assets: must be a list")
    assets = tuple(_asset(a, body, f"source.assets[{i}]") for i, a in enumerate(assets_raw))
    return SourceRecord(
        source_id=check_text(body["source_id"], "source.source_id"),
        kind=check_text(body["kind"], "source.kind"),
        title=check_text(body["title"], "source.title"),
        doi=check_text(body["doi"], "source.doi"),
        url=check_text(body["url"], "source.url"),
        version=check_text(body["version"], "source.version", nullable=True),
        retrieved=check_text(body["retrieved"], "source.retrieved"),
        licenses=tuple(
            _license(x, f"source.licenses[{i}]") for i, x in enumerate(body["licenses"])
        ),
        assets=assets,
        parameters=_parameters(body.get("parameters", {}), "source.parameters"),
        plan_sha256=check_text(body.get("plan_sha256"), "source.plan_sha256", nullable=True),
    )


def load_source_config(path: Path) -> SourceRecord:
    """Load one benchmark config. Offline: reads the YAML file and nothing else."""
    if not path.is_file():
        raise BenchmarkError(f"{path} does not exist", ErrorCode.SOURCE_MISSING)
    try:
        document = load_strict_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise BenchmarkError(f"{path.name}: not valid YAML: {error}") from error
    except (UnicodeDecodeError, OSError) as error:
        raise BenchmarkError(f"{path.name}: cannot be read as UTF-8 text: {error}") from error
    body = _mapping(document, path.name, {"benchmark_config_version", "source"})
    version = body["benchmark_config_version"]
    if type(version) is not int or version != CONFIG_VERSION:
        raise BenchmarkError(
            f"{path.name}: benchmark_config_version {version!r} is not the integer {CONFIG_VERSION}"
        )
    return parse_source(body["source"])


def require_local_asset(asset: AssetRecord, root: Path) -> Path:
    """Path of the asset under `root`, or SOURCE_MISSING. Never fetches anything."""
    path = root / asset.filename
    if not path.is_file():
        raise BenchmarkError(
            f"{asset.filename} not found under {root}; this gate never downloads",
            ErrorCode.SOURCE_MISSING,
        )
    return path
