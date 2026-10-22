# Public content checks

Public source and release packages are checked for signing material, credentials,
excluded local records, retired content and kernel-only helpers. User-mode capture,
proxy loaders and the product's shipped MCP analysis instructions remain supported.

## Before uploading

Install the repository's Git hooks once per clone:

```sh
git config --local core.hooksPath .githooks
```

The pre-commit hook checks the complete staged snapshot, including forced additions
of ignored files. The pre-push hook checks each outgoing ref and every introduced
file version. An intermediate commit that adds and then deletes a credential still
fails. Renamed copies and CRLF conversions of retired content also fail.

Checks can be run directly with Python 3:

```sh
python util/buildscripts/check_public_content.py --staged
python util/buildscripts/check_public_content.py --revision HEAD --base origin/dgcore-main
python util/buildscripts/check_public_content.py --directory path/to/package
python util/buildscripts/check_public_content.py --archive path/to/package.zip
```

Rules report file locations and rule identifiers. Matched values and source lines
are excluded from diagnostics. Reserved identifiers and retired content are stored
as SHA-256 digests. Inspection errors and size/nesting limits fail the check.

## CI and releases

The `Public content policy` check runs for every push and pull request, including
documentation-only changes. Configure it as a required status check on protected
branches. Portable archives are checked again after extraction; automatic publishing
requires successful content, CMake and MSBuild checks for the same commit.

## Historical content

The checks prevent content from being restored into new snapshots or newly pushed
history. Removing data already stored in older commits requires a separate history
rewrite covering affected branches and tags, followed by verification of GitHub PR
references and cached views. Complete pending pull requests before coordinating
that operation. Clean or replace older clones before pushing from them again.

Use GitHub's [sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
for the repository-wide cleanup. Keep removal inventories and credentials outside
the public checkout.
