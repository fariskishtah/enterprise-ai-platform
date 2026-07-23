# Frontend release performance budget

Version 0.9.0 uses route-level code splitting and a WebP login background. The budget
uses raw emitted file size, which is deterministic and more conservative than
network-compressed transfer size.

| Measure | Release limit | Enforcement |
| --- | ---: | --- |
| Initial JavaScript, including static imports | 400 KiB | Fails `npm run build:release` |
| Any individual JavaScript chunk | 500 KiB | Fails release build; Vite also warns |
| Login background image | 300 KiB | Fails release build |
| Total initial static assets | 1 MiB | Fails release build |
| Production chunk-size warnings | Zero at the 500 KiB threshold | Build/release gate |

Dynamic route chunks and the login image are not part of the authenticated application's
initial route unless requested. The login image retains its 2752×1536 aspect ratio and
is encoded once as WebP; the source PNG is retained as an unreferenced provenance asset
until the owner resolves asset licensing. The production build ships only referenced
assets.

Run:

```bash
cd frontend
npm ci
npm run build:release
```

The budget checker reads Vite's generated manifest and prints exact bytes. A budget
increase requires recorded measurements, a customer-impact rationale, and release-owner
approval; it must not be used to mask an accidental regression.
