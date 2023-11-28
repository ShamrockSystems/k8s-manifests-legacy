import hashlib
import logging
import shutil
import subprocess
import time
import typing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PosixPath, WindowsPath

import yaml
from _hashlib import HASH
from yaml import Dumper

VERSION = 'v0.2.0'


@dataclass(slots=True)
class Build:
    name: str
    path: Path
    hash_type: str
    hash: str
    build_datetime_utc: str


def base_to_yaml(dumper: Dumper, data: Build):
    return dumper.represent_dict({
        'name': data.name,
        'path': data.path,
        'hash_type': data.hash_type,
        'hash': data.hash,
        'build_datetime_utc': data.build_datetime_utc
    })


def path_to_yaml(dumper: Dumper, data: Path):
    return dumper.represent_str(str(data))


def main():
    start_perf_time = time.perf_counter()
    logging.basicConfig()
    logger = logging.getLogger('inflate')
    logger.setLevel(logging.DEBUG)

    build_datetime_utc = datetime.utcnow().isoformat()
    logger.info(f'Started inflate {VERSION} at {build_datetime_utc}. Reading lockfile...')

    repo_path = Path(__file__).parent.absolute()

    with open(Path(repo_path, '.inflate.lock.yaml'), encoding='utf-8') as f:
        lock = yaml.load(f, Loader=yaml.Loader)

    sources_path = Path(repo_path, lock['_sources_dir'])
    build_path = Path(repo_path, lock['_build_dir'])

    lock_builds = {}
    for bases_dict in lock['builds']:
        lock_builds[bases_dict['name']] = (Build(
            name=bases_dict['name'],
            path=Path(bases_dict['path']),
            hash_type=bases_dict['hash_type'],
            hash=bases_dict['hash'],
            build_datetime_utc=bases_dict['build_datetime_utc']
        ))
    logger.info(f'Loaded {len(lock_builds)} builds from lockfile')

    source_dirs = set()
    for test in sources_path.iterdir():
        if test.is_dir() and \
                (Path(test, 'kustomization.yml').exists() or
                Path(test, 'kustomization.yaml').exists()):
            source_dirs.add(test)
    logger.info(f'Detected {len(source_dirs)} source directories in {sources_path}')

    build_targets: list[Build] = []
    clean_targets: list[Build] = []
    keep: list[Build] = []

    for lock_build in lock_builds.values():
        if Path(sources_path, lock_build.path) not in source_dirs:
            clean_targets.append(lock_build)
            logger.info(f'Base "{lock_build.name}" is no longer in base directory, added to deflation')
            continue
        source_dirs.remove(Path(sources_path, lock_build.path))
        base_hash = str(dir_hash(
            Path(sources_path, lock_build.path),
            typing.cast(HASH, hashlib.new(lock_build.hash_type))
        ).hexdigest())
        if base_hash != lock_build.hash:
            logger.info(f'Base "{lock_build.name}" hash has changed, added to inflation')
            lock_build.hash = base_hash
            lock_build.build_datetime_utc = build_datetime_utc
            build_targets.append(lock_build)
        else:
            keep.append(lock_build)

    default_hash_type = 'sha256'
    for source_dir in source_dirs:
        build_targets.append(Build(
            name=source_dir.name,
            path=source_dir.relative_to(sources_path),
            hash_type=default_hash_type,
            hash=str(dir_hash(
                Path(sources_path, source_dir),
                typing.cast(HASH, hashlib.new(default_hash_type))
            ).hexdigest()),
            build_datetime_utc=build_datetime_utc
        ))
        logger.info(f'Base "{build_targets[-1].name}" is new, added to build list')

    logger.info(f'Processing {len(build_targets)} build entries')
    for inflation_target in build_targets:
        logger.info(f'Building {Path(sources_path.name, inflation_target.path)}...')
        inflate_kustomization(Path(sources_path, inflation_target.path), sources_path, build_path)
    logger.info(f'Processing {len(clean_targets)} clean entries')
    for deflation_target in clean_targets:
        logger.info(f'Cleaning {Path(build_path.name, deflation_target.path)}...')
        deflate_kustomization(Path(sources_path, deflation_target.path), sources_path, build_path)

    logger.info(f'Writing new lockfile...')
    with open(Path(repo_path, '.inflate.lock.yaml'), 'w', encoding='utf-8') as f:
        yaml.add_representer(Build, base_to_yaml)
        yaml.add_representer(Path, path_to_yaml)
        yaml.add_representer(WindowsPath, path_to_yaml)
        yaml.add_representer(PosixPath, path_to_yaml)
        yaml.dump({
            '_sources_dir': sources_path.relative_to(repo_path),
            '_build_dir': build_path.relative_to(repo_path),
            '_version': VERSION,
            'builds': build_targets + keep
        }, f)

    logger.info(f'Complete in {time.perf_counter() - start_perf_time} seconds')


def dir_hash(path: Path, h: HASH) -> HASH:
    assert Path(path).is_dir()
    for p in sorted(Path(path).iterdir(), key=lambda p: str(p).lower()):
        if p.name == 'charts':
            continue
        h.update(p.name.encode())
        if p.is_file():
            with open(p, 'rb') as f:
                content = f.read()
                try:
                    decoded_content = content.decode('utf-8')
                    normalized_content = decoded_content.replace('\r\n', '\n').replace('\r', '\n')
                    h.update(normalized_content.encode())
                except UnicodeDecodeError:
                    h.update(content)
        elif p.is_dir():
            h = dir_hash(p, h)
    return h


def inflate_kustomization(kustomization_path: Path, bases_path: Path, inflation_path: Path):
    inflation = invoke_kustomize(kustomization_path)
    inflation_target = Path(inflation_path, kustomization_path.relative_to(bases_path))
    inflation_target.mkdir(parents=True, exist_ok=True)

    with open(Path(inflation_target, 'build.yaml'), 'w', encoding='utf-8') as f:
        f.write(inflation)
    with open(Path(inflation_target, 'kustomization.yaml'), 'w', encoding='utf-8') as f:
        f.write('apiVersion: kustomize.config.k8s.io/v1beta1\n'
                'kind: Kustomization\n'
                '\n'
                'resources:\n'
                ' - ./build.yaml\n')
    with open(Path(inflation_target, '.inflated'), 'w', encoding='utf-8') as f:
        f.write('')
    with open(Path(inflation_target, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('# Auto-generated Kustomize base directory\n'
                '**DO NOT EDIT**\n\n'
                'Base generated by `inflate` from '
                f'`{Path(bases_path.name, kustomization_path.relative_to(bases_path))}`.\n')


def deflate_kustomization(kustomization_path: Path, bases_path: Path, inflation_path: Path):
    deflation_target = Path(inflation_path, kustomization_path.relative_to(bases_path))
    shutil.rmtree(deflation_target)


def invoke_kustomize(path: Path) -> str:
    result = subprocess.run(
        ['kubectl', 'kustomize', path.absolute(), '--enable-helm'],
        stdout=subprocess.PIPE, encoding='utf-8',
        text=True, universal_newlines=True)
    if result.returncode != 0:
        raise ChildProcessError
    return result.stdout


if __name__ == "__main__":
    main()
