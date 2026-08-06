#!/usr/bin/env python3
"""Repoint a `pxt staticpkg` build at the FUSE satellite CDN.

`pxt staticpkg --route` can only bake in a root-relative prefix: pxt-core's
internalStaticPkgAsync prepends "/" to any label that isn't already "."- or
"/"-anchored, so passing an absolute https:// route yields "/https://...".
The build is therefore made against a placeholder route and rewritten here.

Three families of URL need repointing:

  1. The placeholder route, which pxt has already stamped through every
     generated file — pxtConfig, script/link tags, the worker bootstraps and
     the rendered docs.
  2. `/trgblb/` — the token pxt swaps for the target blob URL when serving from
     its own CDN. Its static-build replacement table omits it, so the token's
     literal fallback survives into the output and has to be repointed by hand.
  3. `"/static/` — the docs tree is emitted for a host that also serves
     docs/static at /static, an alias pxt relies on hard enough to rewrite
     `/docs/static/` to `/static/` at render time. The CDN has no such alias,
     so both the pre-rendered paths and that render-time rule are repointed at
     the real docs/static directory.

Only text files are touched; anything with a NUL byte in its first 8 KB is
treated as binary and skipped, matching `grep -I`.
"""

import sys
from pathlib import Path

BINARY_SNIFF_BYTES = 8192


def rewrites(placeholder: str, cdn: str, base: str) -> list[tuple[bytes, bytes]]:
    """Ordered (find, replace) pairs. Longest/most specific first."""
    return [
        (placeholder.encode(), f'{cdn}/'.encode()),
        (b'"/trgblb/', f'"{base}/'.encode()),
        (b'"/static/', f'"{base}/docs/static/'.encode()),
    ]


# The editor shell: index.html plus the three files it loads to configure
# itself. index.html is served by Laravel from my.fusestudio.net, so relative
# URLs in any of these resolve against that origin rather than the CDN — these
# are the only files where that is true, and rewriting relative paths anywhere
# else would be wrong.
SHELL_FILES = ('index.html', 'target.json', 'theme.json', 'target.js')


def shell_rewrites(base: str) -> list[tuple[bytes, bytes]]:
    return [
        # appTheme's logos (logo, footerLogo, organizationWideLogo, …) are
        # stored relative and used verbatim as <img src>, so they resolve
        # against my.fusestudio.net and 404. Only the docs/static/ asset family
        # is rewritten: other relative "docs/…" values in target.json are
        # markdown routes for the docs renderer, not URLs.
        (b'"docs/static/', f'"{base}/docs/static/'.encode()),
        # A manifest is fetched no-cors unless the link opts in, and an opaque
        # response can't be parsed — so cross-origin it needs this to load at
        # all. Pairs with manifest-src in MicrobitCspHeaders.
        (b'<link rel="manifest" href="', b'<link rel="manifest" crossorigin="anonymous" href="'),
    ]


def is_binary(data: bytes) -> bool:
    return b'\0' in data[:BINARY_SNIFF_BYTES]


def rewrite_tree(root: Path, pairs: list[tuple[bytes, bytes]]) -> tuple[int, int]:
    scanned = changed = 0

    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue

        data = path.read_bytes()
        if is_binary(data):
            continue

        scanned += 1
        original = data
        for find, replace in pairs:
            data = data.replace(find, replace)

        if data != original:
            path.write_bytes(data)
            changed += 1

    return scanned, changed


def verify(root: Path, placeholder: str) -> list[str]:
    """Catch anything the rewrite missed.

    A surviving placeholder means pxt emitted the route somewhere we did not
    expect. A surviving root-absolute src/href in index.html means a new asset
    reference has appeared that resolves against my.fusestudio.net, where
    nothing is served any more — the exact failure this script exists to
    prevent, and one that is invisible until a student opens the editor.
    """
    problems = []

    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if is_binary(data):
            continue
        if placeholder.encode() in data:
            problems.append(f'{path.relative_to(root)}: placeholder {placeholder} survived the rewrite')

    for name in SHELL_FILES:
        path = root / name
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            for reference in ('src="/', 'href="/', '"docs/static/', '"static/'):
                if reference in line:
                    problems.append(
                        f'{name}:{line_no}: {reference}… resolves against my.fusestudio.net, not the CDN'
                    )

    return problems


def main() -> int:
    if len(sys.argv) != 5:
        print(f'usage: {sys.argv[0]} <build-dir> <placeholder> <cdn-root> <asset-base-url>', file=sys.stderr)
        print(f'  e.g. {sys.argv[0]} built/packaged/microbit /__fuse-satellite__/ '
              'https://dev.satellite.fusestudio.net '
              'https://dev.satellite.fusestudio.net/microbit/abc1234', file=sys.stderr)
        return 2

    root = Path(sys.argv[1])
    placeholder = sys.argv[2]
    # The placeholder stands in for the CDN root; the base is this build's
    # versioned directory under it (.../<app>/<version>).
    cdn = sys.argv[3].rstrip('/')
    base = sys.argv[4].rstrip('/')

    if not (root / 'index.html').is_file():
        print(f'error: {root}/index.html not found — did pxt staticpkg run?', file=sys.stderr)
        return 1

    scanned, changed = rewrite_tree(root, rewrites(placeholder, cdn, base))
    print(f'rewrote {changed} of {scanned} text files under {root} -> {base}')

    for name in SHELL_FILES:
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        for find, replace in shell_rewrites(base):
            data = data.replace(find, replace)
        path.write_bytes(data)

    problems = verify(root, placeholder)
    if problems:
        print('\nerror: build still references paths that will not resolve:', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 1

    print('verified: no placeholder or root-absolute references remain')
    return 0


if __name__ == '__main__':
    sys.exit(main())
