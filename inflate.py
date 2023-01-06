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

VERSION = 'v0.1.0'


@dataclass(slots=True)
class Base:
    name: str
    path: Path
    hash_type: str
    hash: str
    build_datetime_utc: str


def base_to_yaml(dumper: Dumper, data: Base):
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

    bases_path = Path(repo_path, lock['_bases_dir'])
    inflation_path = Path(repo_path, lock['_inflated_dir'])

    lock_bases = {}
    for bases_dict in lock['bases']:
        lock_bases[bases_dict['name']] = (Base(
            name=bases_dict['name'],
            path=Path(bases_dict['path']),
            hash_type=bases_dict['hash_type'],
            hash=bases_dict['hash'],
            build_datetime_utc=bases_dict['build_datetime_utc']
        ))
    logger.info(f'Loaded {len(lock_bases)} bases from lockfile')

    bases_dirs = set()
    for test in bases_path.iterdir():
        if test.is_dir() and \
                (Path(test, 'kustomization.yml').exists() or
                 Path(test, 'kustomization.yaml').exists()):
            bases_dirs.add(test)
    logger.info(f'Detected {len(bases_dirs)} base directories in {bases_path}')

    inflation_targets: list[Base] = []
    deflation_targets: list[Base] = []
    keep: list[Base] = []

    for lock_base in lock_bases.values():
        if Path(bases_path, lock_base.path) not in bases_dirs:
            deflation_targets.append(lock_base)
            logger.info(f'Base "{lock_base.name}" is no longer in base directory, added to deflation')
            continue
        bases_dirs.remove(Path(bases_path, lock_base.path))
        base_hash = str(dir_hash(
            Path(bases_path, lock_base.path),
            typing.cast(HASH, hashlib.new(lock_base.hash_type))
        ).hexdigest())
        if base_hash != lock_base.hash:
            logger.info(f'Base "{lock_base.name}" hash has changed, added to inflation')
            lock_base.hash = base_hash
            lock_base.build_datetime_utc = build_datetime_utc
            inflation_targets.append(lock_base)
        else:
            keep.append(lock_base)

    default_hash_type = 'sha256'
    for base_dir in bases_dirs:
        inflation_targets.append(Base(
            name=base_dir.name,
            path=base_dir.relative_to(bases_path),
            hash_type=default_hash_type,
            hash=str(dir_hash(
                Path(bases_path, base_dir),
                typing.cast(HASH, hashlib.new(default_hash_type))
            ).hexdigest()),
            build_datetime_utc=build_datetime_utc
        ))
        logger.info(f'Base "{inflation_targets[-1].name}" is new, added to inflation')

    logger.info(f'Processing {len(inflation_targets)} inflation entries')
    for inflation_target in inflation_targets:
        inflate_kustomization(Path(bases_path, inflation_target.path), bases_path, inflation_path)
    logger.info(f'Processing {len(deflation_targets)} deflation entries')
    for deflation_target in deflation_targets:
        deflate_kustomization(Path(bases_path, deflation_target.path), bases_path, inflation_path)

    logger.info(f'Writing new lockfile...')
    with open(Path(repo_path, '.inflate.lock.yaml'), 'w', encoding='utf-8') as f:
        yaml.add_representer(Base, base_to_yaml)
        yaml.add_representer(Path, path_to_yaml)
        yaml.add_representer(WindowsPath, path_to_yaml)
        yaml.add_representer(PosixPath, path_to_yaml)
        yaml.dump({
            '_bases_dir': bases_path.relative_to(repo_path),
            '_inflated_dir': inflation_path.relative_to(repo_path),
            '_version': VERSION,
            'bases': inflation_targets + keep
        }, f)

    logger.info(f'Complete in {time.perf_counter() - start_perf_time} seconds')


def dir_hash(path: Path, h: HASH) -> HASH:
    assert Path(path).is_dir()
    for p in sorted(Path(path).iterdir(), key=lambda p: str(p).lower()):
        if p.name != 'charts':  # TODO parse .gitignore in the future
            h.update(p.name.encode())
        if p.is_file():
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    h.update(chunk)
        elif p.is_dir() and p.name != 'charts':  # TODO parse .gitignore in the future
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
