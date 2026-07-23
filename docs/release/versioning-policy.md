# Versioning policy

## Canonical source

The root `VERSION` file is the canonical application release version. It contains
one SemVer value and a trailing newline. Backend package metadata and frontend
package metadata are synchronized projections. The backend runtime reads
`VERSION` directly, so FastAPI/OpenAPI metadata uses the canonical value.

`scripts/check-release-version.py` fails when `VERSION`,
`backend/pyproject.toml`, `frontend/package.json`, or the root entry in
`frontend/package-lock.json` disagree.

## Semantic versioning

- `MAJOR`: incompatible API, persisted-data, or supported-operation change.
- `MINOR`: backward-compatible product capability or materially expanded pilot
  scope.
- `PATCH`: backward-compatible defect, security, documentation, or operational
  correction.

Pre-1.0 releases may still contain significant product limitations. Those
limitations must be stated in `docs/release/supported-scope.md`.

## Release candidates and tags

- Release candidate version: `X.Y.Z-rc.N`.
- Final Git tag: `vX.Y.Z`.
- Candidate Git tag: `vX.Y.Z-rc.N`.
- Tags must identify a reviewed commit with green release validation evidence.
- A tag must never be moved or reused.

## Changelog

Keep changes under `Unreleased` while developing. At release, create one section
matching `VERSION`, record the release date, and describe supported behavior
without implying deferred capabilities. Historical entries are not rewritten;
incorrect unreleased positioning may be corrected with a clear note.

## Docker images

Published images, when a registry workflow is approved, must receive immutable
commit-SHA and `vX.Y.Z` tags. `latest` is not a release identity. Image labels
and SBOM/provenance evidence must record the same version and commit.

The current repository builds images locally and does not publish them.

## Compatibility expectations

- Public HTTP contracts remain backward compatible within one minor line unless
  a documented security correction requires otherwise.
- Alembic migrations are forward-applied before new application processes start.
- Application rollback is supported only when the older application is
  compatible with the already-applied schema.
- Dataset versions, registered models, audit records, and citations remain
  immutable after reaching their terminal states.

## Update responsibility

The release owner updates `VERSION`, synchronized package projections, and
`CHANGELOG.md` in one reviewable change. CI runs the version consistency check.
No runtime environment variable may silently create a different product
version.
