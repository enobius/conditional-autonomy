"""S2-01 development-candidate integrity and fail-closed authority boundary.

Approval records are trusted, audited owner inputs, not authentication tokens.
This module deliberately cannot authorize confirmatory collection; S2-15
owns the separately approved final-freeze gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from collections.abc import Mapping

from .storage import canonical_json_bytes


class Stage2AuthorityError(ValueError):
    pass


def artifact_set_hash(artifacts: list) -> str:
    return hashlib.sha256(canonical_json_bytes(artifacts)).hexdigest()


def verify_development_pin_integrity(root: Path, record: Mapping) -> None:
    if record.get('schema_version') != '1.0' or record.get('scope') != 'DEVELOPMENT_CANDIDATE':
        raise Stage2AuthorityError('not a supported development candidate')
    artifacts = record.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise Stage2AuthorityError('missing pinned artifact inventory')
    if record.get('artifact_set_hash') != artifact_set_hash(artifacts):
        raise Stage2AuthorityError('artifact inventory binding changed')
    root = root.resolve()
    seen = set()
    for item in artifacts:
        if not isinstance(item, Mapping) or set(item) != {'path', 'sha256', 'bytes'}:
            raise Stage2AuthorityError('invalid artifact descriptor')
        name = item['path']
        if not isinstance(name, str) or '\\' in name or ':' in name:
            raise Stage2AuthorityError('artifact path is not repository-relative')
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or name in seen:
            raise Stage2AuthorityError('unsafe or duplicate artifact path')
        seen.add(name)
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise Stage2AuthorityError('artifact missing or outside repository')
        data = path.read_bytes()
        if type(item['bytes']) is not int or len(data) != item['bytes']:
            raise Stage2AuthorityError('artifact byte count changed')
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise Stage2AuthorityError('artifact content changed')


def require_stage2_authority(root: Path, record: Mapping, *, phase: str) -> None:
    if phase != 'development':
        raise Stage2AuthorityError('draft authority cannot authorize confirmatory collection')
    verify_development_pin_integrity(root, record)
    approval = record.get('owner_approval')
    if not isinstance(approval, Mapping) or approval.get('approved') is not True:
        raise Stage2AuthorityError('exact development pin needs owner approval')
    if (approval.get('artifact_set_hash') != record['artifact_set_hash']
            or not isinstance(approval.get('owner'), str) or not approval['owner'].strip()
            or not isinstance(approval.get('statement'), str) or not approval['statement'].strip()
            or not isinstance(approval.get('draft_commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', approval['draft_commit'])):
        raise Stage2AuthorityError('owner approval is not bound to artifacts and draft commit')
    # This approval covers the draft pin only. Pilot execution additionally
    # requires S2-13 input/config pins, resolved policy and paid-run authority.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--phase', choices=['development', 'confirmatory'], default='development')
    parser.add_argument('--verify-candidate', action='store_true')
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding='utf-8'))
        if not isinstance(record, Mapping):
            raise Stage2AuthorityError('record must be an object')
        if args.verify_candidate:
            verify_development_pin_integrity(args.root, record)
            print('Candidate artifact integrity: PASS (not execution authority)')
        else:
            require_stage2_authority(args.root, record, phase=args.phase)
            print('Development pin approval: PASS (not pilot execution authority)')
    except (Stage2AuthorityError, OSError, ValueError, TypeError, KeyError) as error:
        print('Stage 2 authority: BLOCKED — ' + str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
