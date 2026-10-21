# Third-party licenses

The repository is MIT licensed (`LICENSE`), with the exception below. The MIT
license does not cover these files; they stay under their own license.

## Public Suffix List extract

- File: `scripts/hooks/public-suffix-list.json`
- What it is: a filtered extract of the Public Suffix List
  (https://publicsuffix.org/list/), `public_suffix_list.dat` of
  github.com/publicsuffix/list at commit
  `5dd321ffe02039e2431382a095cf80e27ff5eb94`. The commit, the git blob id and
  the sha256 of the source are recorded in the file itself.
- License: Mozilla Public License 2.0, not MIT. Full text:
  `LICENSES/MPL-2.0.txt`, also at https://mozilla.org/MPL/2.0/. The original
  license notice is kept unchanged in the file's `_license` field.
- How it is made: `scripts/gen-public-suffix-list.mjs` (MIT) from the
  upstream `.dat`; the file is not edited by hand. The code that loads it
  (`scripts/hooks/egress-gate.mjs`, `src/web/agent-scaffold.ts`) is a separate
  file under MIT.
