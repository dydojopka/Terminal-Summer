#!/usr/bin/env python3
"""Упаковывает готовую сборку со сценариями и лицензиями: TAR.GZ для Linux, ZIP для Windows."""

from __future__ import annotations

import argparse
import ast
import hashlib
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
import zipfile

from packaging.utils import canonicalize_name
from PyInstaller.archive.readers import CArchiveReader


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from file_io import atomic_output
from story.resources import RELEASE_SCRIPTS


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


def analyzed_files(path: Path) -> dict[str, tuple[Path, str]]:
    # TOC PyInstaller — Python-литерал. Читаем записи, не исполняя .spec.
    return {
        entry[0].replace("\\", "/"): (Path(entry[1]).resolve(), entry[2])
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


def arch_notices(source: Path, output: Path) -> bool:
    if not shutil.which("pacman"):
        return False
    query = subprocess.run(["pacman", "-Qoq", str(source)], capture_output=True, text=True)
    if query.returncode or len(query.stdout.splitlines()) != 1:
        return False
    package = query.stdout.strip()
    license_dir = Path("/usr/share/licenses") / package
    files = {path.relative_to(license_dir): path for path in license_dir.rglob("*") if path.is_file()}
    if package in {"libgcc", "libstdc++"}:
        gpl = Path("/usr/share/licenses/spdx/GPL-3.0-only.txt")
        if gpl.is_file():
            files[Path(gpl.name)] = gpl
    for relative, path in sorted(files.items()):
        copy_file(path, output / "LICENSES" / "native" / package / relative)
    return bool(files)


def download_source(output: Path, url: str, expected_sha256: str) -> Path:
    path = output / "sources" / PurePosixPath(url).name
    path.parent.mkdir(exist_ok=True)
    with urlopen(url, timeout=60) as response, path.open("xb") as file:
        shutil.copyfileobj(response, file)
    if sha256(path) != expected_sha256:
        raise ValueError(f"Не совпал SHA-256 исходников: {path.name}")
    return path


def collect_scenarios(archive: CArchiveReader, output: Path) -> None:
    # Берём тексты собранной версии, а не потенциально изменившееся рабочее дерево.
    # PyInstaller помечает DATA как 'b', если os.access(path, X_OK) возвращает
    # True. На Windows это возможно и для TXT/JSON; ниже отбираем их по пути.
    data = {name.replace("\\", "/"): name for name, entry in archive.toc.items() if entry[-1] in {"x", "b"}}
    originals = {f"TS/text/{name}" for name in RELEASE_SCRIPTS}
    chapters = {f"TS/text/en/{Path(name).stem}.json" for name in RELEASE_SCRIPTS}
    missing = (originals | chapters) - data.keys()
    if missing:
        raise ValueError("В бинарнике нет обязательных сценариев или перевода: " + ", ".join(sorted(missing)))
    translations = {name for name in data if re.fullmatch(r"TS/text/en/[a-z0-9_-]+\.json", name)}
    translations.discard("TS/text/en/import-report.json")
    for name in sorted(originals | translations):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extract(data[name]))


def collect(binary: Path, analysis: Path, output: Path, *, download: bool) -> list[str]:
    archive = CArchiveReader(str(binary))
    analyzed = analyzed_files(analysis)
    pure = archive.open_embedded_archive("PYZ.pyz").toc
    shipped = set(pure) | {name.replace("\\", "/") for name in archive.toc}
    used_paths = {analyzed[name][0] for name in shipped if name in analyzed}
    distributions = {}
    owned_paths = set()
    for dist in metadata.distributions():
        name = canonicalize_name(dist.metadata["Name"])
        files = {dist.locate_file(path).resolve() for path in dist.files or ()}
        matched = files & used_paths
        if matched or name == "pyinstaller":  # bootloader вне архива onefile
            distributions[name] = dist
            owned_paths.update(matched)

    if not {"certifi", "pygame-ce"} <= distributions.keys():
        raise ValueError("Analysis-00.toc не соответствует аудио/сетевым компонентам сборки")

    collect_scenarios(archive, output)
    for file in ("README.md", "LICENSE", "LICENSING.md"):
        copy_file(ROOT / file, output / file)
    issues = []
    source_links = []
    for name, dist in sorted(distributions.items()):
        notices = package_notices(dist, output)
        if not notices:
            issues.append(f"Не найден текст лицензии пакета {name} {dist.version}")
        if name in ("certifi", "pygame-ce"):
            pair = SOURCES.get((name, dist.version))
            if pair is None:
                issues.append(f"Не зафиксирован архив исходников {name} {dist.version}")
            else:
                url, digest = pair
                link = url
                if download:
                    source = download_source(output, url, digest)
                    link = source.relative_to(output).as_posix()
                    if name == "pygame-ce":
                        # В wheel есть LGPL.txt, но не все уведомления кодеков из sdist.
                        with tarfile.open(source, "r:gz") as tar:
                            for item in tar:
                                if item.isfile() and "/docs/licenses/LICENSE." in item.name:
                                    target = output / "LICENSES" / "pygame-ce-native" / PurePosixPath(item.name).name
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    with tar.extractfile(item) as stream:
                                        target.write_bytes(stream.read())
                else:
                    issues.append(f"В комплект не скачаны исходники {name} {dist.version}")
                source_links.append(f"- [{name} {dist.version}]({link})\n")

    stdlib = Path(sysconfig.get_path("stdlib"))
    python_license = next((file for file in (Path(sys.base_prefix) / "LICENSE.txt", stdlib / "LICENSE.txt")
                           if file.is_file()), None)
    if python_license is None:
        issues.append("Не найден LICENSE.txt использованного интерпретатора Python")
    else:
        copy_file(python_license, output / "LICENSES" / "Python" / "LICENSE.txt")

    extension_dirs = {(stdlib / "lib-dynload").resolve(), (Path(sys.base_prefix) / "DLLs").resolve()}
    arch_packages = {}
    for raw_name, entry in sorted(archive.toc.items()):
        if entry[-1] != "b":
            continue
        name = raw_name.replace("\\", "/")
        source, kind = analyzed.get(name, (None, None))
        if kind == "DATA":
            continue  # Не все записи с типом 'b' — нативные библиотеки.
        if source in owned_paths or re.fullmatch(
            r"(?:libpython[0-9.]+\.so(?:\.[0-9.]+)?|python[0-9]+t?\.dll)", name, flags=re.I
        ):
            continue
        if source and source.parent in extension_dirs and source.suffix in {".so", ".pyd"}:
            continue  # Расширение CPython; отдельно упакованные DLL/.so проверяются ниже.
        if source is not None and source not in arch_packages:
            arch_packages[source] = arch_notices(source, output)
        if not arch_packages.get(source):
            issues.append(f"Сверить правовой статус и уведомления нативного файла {name}")

    issues.append("Сверить версии, уведомления и исходники нативных LGPL-компонентов; "
                  "проверить пересборку с заменой библиотеки.")
    (output / "THIRD_PARTY_NOTICES.md").write_text(
        "# Сторонние компоненты Terminal Summer\n\n"
        "Собственная CC BY-NC-SA не распространяется на эти библиотеки. "
        "В сборке используется pygame-ce под LGPL-2.1-or-later и certifi под MPL-2.0. "
        "Тексты лицензий и уведомления находятся в `LICENSES/`.\n\n"
        "## Исходники Python-пакетов\n\n" + "".join(source_links),
        encoding="utf-8",
    )
    return issues


def package_release(binary: Path, analysis: Path, output: Path, *, download: bool) -> list[str]:
    archive_name = output.name.lower()
    if not archive_name.endswith((".tar.gz", ".zip")):
        raise ValueError("Имя архива должно оканчиваться на .tar.gz или .zip")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=output.parent) as temporary:
        support = Path(temporary)
        issues = collect(binary, analysis, support, download=download)
        members = [(binary, binary.name)]
        members.extend((path, path.relative_to(support).as_posix())
                       for path in sorted(support.rglob("*")) if path.is_file())
        with atomic_output(output, overwrite=False) as target:
            if archive_name.endswith(".tar.gz"):
                with tarfile.open(fileobj=target, mode="w:gz", dereference=True) as archive:
                    for path, name in members:
                        archive.add(path, arcname=name, recursive=False)
            else:
                with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for path, name in members:
                        archive.write(path, name)
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("analysis", type=Path, help="Analysis-00.toc от этой сборки")
    parser.add_argument("--output", type=Path, help="Путь к новому .tar.gz или .zip (по умолчанию в build/release/)")
    parser.add_argument("--download-sources", action="store_true", help="Скачать проверяемые архивы certifi и pygame-ce")
    args = parser.parse_args()
    extension = ".zip" if args.binary.suffix.lower() == ".exe" else ".tar.gz"
    output = args.output or ROOT / "build" / "release" / f"{args.binary.stem}{extension}"
    try:
        issues = package_release(args.binary, args.analysis, output, download=args.download_sources)
    except FileExistsError:
        parser.exit(1, f"Архив уже существует: {output}. Укажите новый путь через --output.\n")
    except Exception as exc:
        parser.exit(1, f"Не удалось подготовить архив: {exc}\n")
    print(f"Архив: {output}")
    print("Проверки до публикации:", file=sys.stderr)
    for issue in issues:
        print(f"- {issue}", file=sys.stderr)


if __name__ == "__main__":
    main()
