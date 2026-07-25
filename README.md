# alpine-edipipe

Shared X12 EDI engine for the Alpine / First Medical MMIS platform — the single
source of truth for X12 parsing (`edipipe.read`) and generation (`edipipe.write`)
across all transaction sets exchanged between First Medical (MCO) and ASES/PRMMIS.

Stdlib-only, no third-party runtime dependencies.

## Layout

- `edipipe.core` — transaction-agnostic envelope walk + builder (`parse_envelope`, `build_interchange`)
- `edipipe.read` — readers: 835, 999/277CA acks, 820, 834, 837I, 270/271, 276/277, 278
- `edipipe.write` — generators: 837I/837P (`generate_x12`)

## Use as a submodule

Vendored into each app as a git submodule and installed:

```bash
git submodule add https://github.com/CentNes/alpine-edipipe vendor/alpine-edipipe
pip install ./vendor/alpine-edipipe
```

Then `import edipipe` / `from edipipe.write import generate_x12` as usual.

## Develop

```bash
pip install -e .[dev]
pytest
```
