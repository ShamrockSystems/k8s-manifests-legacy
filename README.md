<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://s3.shamrock.systems/shamrock-static-assets/logos/shamrock-wide-1500-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://s3.shamrock.systems/shamrock-static-assets/logos/shamrock-wide-1500-light.png">
  <img alt="Shamrock logo" src="https://s3.shamrock.systems/shamrock-static-assets/logos/shamrock-wide-1500-flat-gray.png">
</picture>

# Shamrock Kubernetes Cluster Manifests

Kubernetes manifests, Helm values, and Kustomizations used to configure releases on the Shamrock Kubernetes cluster. All
releases are Kustomizations.

## Setup Repository

1. Install [Python](https://www.python.org/) (Version specified in `pyproject.toml`)
2. Install [Poetry](https://python-poetry.org/)
3. `poetry install`
4. `poetry run task pre-commit-hook`

## Structure

- `external/` Kustomize external manifests, automatically built by `inflate` to `generated/`
- `generated/` Kustomize builds from external sources
- `releases/` Release Kustomizations

## Tooling

This repository prohibits the committing of `Secret` manifests. Please use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) instead. For example:

```sh
kubeseal -f secret.bookstack.yaml -w sealedsecret.yaml
```

Helm charts are configured using Kustomizations in `external/`, to retrieve values for a given chart, use:

```sh
helm show values repo/chart > .\values.yaml
```

Use `poetry shell` to enable the Python virtual environment.

Use `poetry run task pre-commit` to run `pre-commit` at any time, or just wait to `git commit`.

Use `poetry run task inflate` to inflate Kustomizations from the `external/` directory to the `generated/` directory.
This allows releases that reference external assets to be properly versioned in the repository without dependence on the
liveness or consistency of those sources.

*`inflate` hashes are currently being calculated on machines with UNIX line endings. Inflates generated on Windows will be different if checking out as `CRLF`. Consider checking out this repository as `LF`.
