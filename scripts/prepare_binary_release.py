#!/usr/bin/env python3
"""Собирает локальный комплект бинарного релиза и отчёт о сторонних компонентах."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from importlib import metadata
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from urllib.request import urlopen

from packaging.utils import canonicalize_name
from PyInstaller.archive.readers import CArchiveReader


ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    ("certifi", "2026.2.25"): (
        "https://files.pythonhosted.org/packages/af/2d/7bf41579a8986e348fa033a31cdd0e4121114f6bce2457e8876010b092dd/certifi-2026.2.25.tar.gz",
        "e887ab5cee78ea814d3472169153c2d12cd43b14bd03329a39a9c6e2e80bfba7",
    ),
    ("pygame-ce", "2.5.8"): (
        "https://files.pythonhosted.org/packages/26/2d/0f942ec31d558a6a1f2fd0df9965ff0055f165ed5b8d36f6509b1f3768a2/pygame_ce-2.5.8.tar.gz",
        "3c8e69088ead310037972c391306ea58e74d7296b35d1890067749235fd554ba",
    ),
}


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyzed_files(path: Path) -> dict[str, Path]:
    # TOC PyInstaller — Python-литерал. Читаем записи, не исполняя .spec.
    return {
        entry[0].replace("\\", "/"): Path(entry[1]).resolve()
        for section in ast.literal_eval(path.read_text(encoding="utf-8"))
        if isinstance(section, (tuple, list))
        for entry in section
        if isinstance(entry, tuple) and len(entry) == 3 and entry[2] in {
            "PYMODULE", "PYSOURCE", "EXTENSION", "BINARY", "DATA",
        }
    }


def package_notices(dist: metadata.Distribution, output: Path) -> list[str]:
    notices = []
    for relative in dist.files or ():
        if ".." in relative.parts or relative.is_absolute():
            continue
        if not relative.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT", "NOTICE", "AUTHORS", "LGPL")):
            continue
        if not dist.locate_file(relative).is_file():
            continue
        target = f"LICENSES/python/{canonicalize_name(dist.metadata['Name'])}/{relative.as_posix()}"
        copy_file(dist.locate_file(relative), output / target)
        notices.append(target)
    return sorted(notices)


def arch_notices(source: Path, output: Path) -> tuple[str, list[str]] | None:
    if not shutil.which("pacman"):
        return None
    query = subprocess.run(["pacman", "-Qoq", str(source)], capture_output=True, text=True)
    if query.returncode or len(query.stdout.splitlines()) != 1:
        return None
    package = query.stdout.strip()
    package_version = subprocess.check_output(["pacman", "-Q", package], text=True).strip()
    notices = []
    license_dir = Path("/usr/share/licenses") / package
    for path in sorted(license_dir.rglob("*")):
        if path.is_file():
            target = f"LICENSES/native/{package}/{path.relative_to(license_dir).as_posix()}"
            copy_file(path, output / target)
            notices.append(target)
    if package in {"libgcc", "libstdc++"}:
        gpl = Path("/usr/share/licenses/spdx/GPL-3.0-only.txt")
        if gpl.is_file():
            target = f"LICENSES/native/{package}/{gpl.name}"
            copy_file(gpl, output / target)
            notices.append(target)
    return package_version, notices


def download_source(output: Path, url: str, expected_sha256: str) -> Path:
    path = output / "sources" / PurePosixPath(url).name
    path.parent.mkdir(exist_ok=True)
    with urlopen(url, timeout=60) as response, path.open("xb") as file:
        shutil.copyfileobj(response, file)
    if sha256(path) != expected_sha256:
        raise ValueError(f"Не совпал SHA-256 исходников: {path.name}")
    return path


def collect(binary: Path, analysis: Path, output: Path, *, download: bool) -> None:
    archive = CArchiveReader(str(binary))
    analyzed = analyzed_files(analysis)
    pure = archive.open_embedded_archive("PYZ.pyz").toc
    shipped = set(pure) | {name.replace("\\", "/") for name in archive.toc}
    used_paths = {analyzed[name] for name in shipped if name in analyzed}
    distributions = {}
    owners = {}
    for dist in metadata.distributions():
        name = canonicalize_name(dist.metadata["Name"])
        files = {dist.locate_file(path).resolve() for path in dist.files or ()}
        matched = files & used_paths
        if matched or name == "pyinstaller":  # bootloader вне архива onefile
            distributions[name] = dist
            owners.update(dict.fromkeys(matched, name))

    if not {"certifi", "pygame-ce"} <= distributions.keys():
        raise ValueError("Analysis-00.toc не соответствует аудио/сетевым компонентам сборки")

    copy_file(binary, output / binary.name)
    for file in ("LICENSE", "LICENSING.md"):
        copy_file(ROOT / file, output / file)
    issues = []
    packages = []
    for name, dist in sorted(distributions.items()):
        notices = package_notices(dist, output)
        if not notices:
            issues.append(f"Не найден текст лицензии пакета {name} {dist.version}")
        record = {"name": name, "version": dist.version, "notices": notices}
        if name in ("certifi", "pygame-ce"):
            pair = SOURCES.get((name, dist.version))
            if pair is None:
                issues.append(f"Не зафиксирован архив исходников {name} {dist.version}")
            else:
                url, digest = pair
                record.update(source_url=url, source_sha256=digest)
                if download:
                    source = download_source(output, url, digest)
                    record["source_archive"] = source.relative_to(output).as_posix()
                    if name == "pygame-ce":
                        # В wheel есть LGPL.txt, но не все уведомления кодеков из sdist.
                        with tarfile.open(source, "r:gz") as tar:
                            for item in tar:
                                if item.isfile() and "/docs/licenses/LICENSE." in item.name:
                                    target = output / "LICENSES" / "pygame-ce-native" / PurePosixPath(item.name).name
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    with tar.extractfile(item) as stream:
                                        target.write_bytes(stream.read())
                                    notices.append(target.relative_to(output).as_posix())
                else:
                    issues.append(f"В комплект не скачаны исходники {name} {dist.version}")
        packages.append(record)

    stdlib = Path(sysconfig.get_path("stdlib"))
    python_license = next((file for file in (Path(sys.base_prefix) / "LICENSE.txt", stdlib / "LICENSE.txt")
                           if file.is_file()), None)
    if python_license is None:
        issues.append("Не найден LICENSE.txt использованного интерпретатора Python")
    else:
        copy_file(python_license, output / "LICENSES" / "Python" / "LICENSE.txt")

    native = []
    arch_packages = {}
    for raw_name, entry in sorted(archive.toc.items()):
        if entry[-1] != "b":
            continue
        name = raw_name.replace("\\", "/")
        source = analyzed.get(name)
        record = {"file": name}
        if source is not None and source in owners:
            record["package"] = owners[source]
        elif re.fullmatch(r"(?:libpython[0-9.]+\.so(?:\.[0-9.]+)?|python[0-9]+t?\.dll)", name, flags=re.I):
            record["package"] = "Python"
        else:
            if source is not None and source not in arch_packages:
                arch_packages[source] = arch_notices(source, output)
            found = arch_packages.get(source)
            if found:
                record["package"], record["notices"] = found
            if not found or not record["notices"]:
                issues.append(f"Сверить правовой статус и уведомления нативного файла {name}")
        native.append(record)

    issues.append("Сверить версии, уведомления и исходники нативных LGPL-компонентов; "
                  "проверить пересборку с заменой библиотеки.")
    source_links = []
    for record in packages:
        if "source_url" in record:
            link = record.get("source_archive", record["source_url"])
            source_links.append(f"- [{record['name']} {record['version']}]({link})\n")
    (output / "THIRD_PARTY_NOTICES.md").write_text(
        "# Сторонние компоненты Terminal Summer\n\n"
        f"Python {sys.version.split()[0]}, {sys.platform}. SHA-256 бинарника: `{sha256(binary)}`.\n\n"
        "Собственная CC BY-NC-SA не распространяется на эти библиотеки. "
        "В сборке используется pygame-ce под LGPL-2.1-or-later и certifi под MPL-2.0. "
        "См. тексты в `LICENSES/` и список компонентов в `components.json`.\n\n"
        "## Исходники Python-пакетов\n\n" + "".join(source_links) + "\n"
        "## Проверки до публикации\n\n" + "".join(f"- {issue}\n" for issue in issues),
        encoding="utf-8",
    )
    (output / "components.json").write_text(
        json.dumps({"python": sys.version.split()[0], "packages": packages, "native": native},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("analysis", type=Path, help="Analysis-00.toc от этой сборки")
    parser.add_argument("--download-sources", action="store_true", help="Скачать проверяемые архивы certifi и pygame-ce")
    args = parser.parse_args()
    staging = ROOT / "build" / "release"
    staging.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"{args.binary.stem}-", dir=staging))
    try:
        collect(args.binary, args.analysis, output, download=args.download_sources)
    except Exception as exc:
        shutil.rmtree(output)
        parser.exit(1, f"Не удалось подготовить комплект: {exc}\n")
    print(f"Комплект для проверки: {output}")
    print("Перед публикацией см. THIRD_PARTY_NOTICES.md и LICENSING.md в комплекте.")


if __name__ == "__main__":
    main()
