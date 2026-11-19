# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private reporting instead:
<https://github.com/projectbin07-stack/print-forge/security/advisories/new>.

Include a description, the input that triggers the problem and the version you used. Reports are
handled on a best-effort basis by a single maintainer.

## Scope

print-forge reads parts files (TOML) and command-line parameters, and writes STL, 3MF, CSV, JSON
and HTML files to the paths it is given. It makes no network requests and never executes file
content. Reports of interest include crashes or runaway CPU/memory on crafted parameters or parts
files, and HTML injection through part names or legend text into the catalogue.
