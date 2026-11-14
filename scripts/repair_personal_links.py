"""Back up and remove verified legacy bookmark copies for one owner's project.

Default is read-only. Example: python -m scripts.repair_personal_links --project-id 7 --owner-id 4
Use --apply only after reviewing the counts. Never infer ownership from administrator roles.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

from sqlalchemy import select

from app.models import ProjectLink, SiteProject, User, UserLink, UserLinkCategory, UserLinkMigration, Workspace


def repair_plan(db, project_id, owner_id):
    project = db.get(SiteProject, project_id)
    workspace = db.get(Workspace, project.workspace_id) if project else None
    if not workspace or workspace.owner_id != owner_id:
        raise ValueError('The verified owner must own this project workspace.')
    legacy = list(db.scalars(select(ProjectLink).where(ProjectLink.site_project_id == project_id).with_for_update()))
    owner_links = list(db.scalars(select(UserLink).where(UserLink.owner_user_id == owner_id).with_for_update()))
    if any(not any(p.name == l.name and p.url == l.url for p in owner_links) for l in legacy):
        raise ValueError('Owner is missing legacy URLs; refusing to remove shared source.')
    markers = {(m.owner_user_id, m.legacy_link_id) for m in db.scalars(select(UserLinkMigration))}
    categories = list(db.scalars(select(UserLinkCategory).where(
        UserLinkCategory.owner_user_id != owner_id,
        UserLinkCategory.name == ('原项目 · ' + project.name)[:80],
    ).with_for_update()))
    candidates = []
    retained = []
    for category in categories:
        personal = list(db.scalars(select(UserLink).where(UserLink.category_id == category.id).with_for_update()))
        for link in personal:
            matches = [old for old in legacy if (link.owner_user_id, old.id) in markers
                and link.owner_user_id == category.owner_user_id
                and link.name == old.name and link.url == old.url]
            # Old versions also copied notes. Require the owner's original notes
            # or an empty value, so a member's custom note is never discarded.
            originals = [p for p in owner_links if p.name == link.name and p.url == link.url]
            if len(matches) == 1 and any(link.notes in (None, '', p.notes) for p in originals):
                candidates.append(link)
            else:
                retained.append(link)
    return legacy, candidates, categories, retained


def repair(db, project_id, owner_id, backup_dir):
    # Serialize against personal-link CRUD before collecting or deleting records.
    list(db.scalars(select(User).order_by(User.id).with_for_update()))
    legacy, candidates, categories, retained = repair_plan(db, project_id, owner_id)
    models = [ProjectLink, UserLink, UserLinkCategory, UserLinkMigration]
    snapshot = {
        model.__tablename__: [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in db.scalars(select(model).order_by(model.id))
        ] for model in models
    }
    snapshot['repair'] = {'project_id': project_id, 'owner_id': owner_id,
        'removed_personal_ids': [row.id for row in candidates],
        'removed_legacy_ids': [row.id for row in legacy],
        'retained_ambiguous_ids': [row.id for row in retained]}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / ('personal-links-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    # Exclusive creation and completed backup precede all mutations.
    with target.open('x', encoding='utf-8') as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2, default=str)
    for row in candidates:
        db.delete(row)
    db.flush()
    removed_categories = 0
    for category in categories:
        if not db.scalar(select(UserLink.id).where(UserLink.category_id == category.id).limit(1)):
            db.delete(category)
            removed_categories += 1
    for row in legacy:
        db.delete(row)
    db.flush()
    # Caller controls the transaction; migration markers are deliberately retained.
    return {'removed_copies': len(candidates), 'removed_categories': removed_categories,
        'archived_shared_sources': len(legacy), 'retained_for_review': len(retained), 'backup': str(target.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', type=int, required=True)
    parser.add_argument('--owner-id', type=int, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', default='backups/personal-links-repair')
    args = parser.parse_args()
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        if args.apply:
            result = repair(db, args.project_id, args.owner_id, args.backup_dir)
            db.commit()
        else:
            legacy, candidates, categories, retained = repair_plan(db, args.project_id, args.owner_id)
            result = {'dry_run': True, 'copies_to_remove': len(candidates),
                'legacy_sources_to_archive': len(legacy), 'retained_for_review': len(retained)}
            db.rollback()
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
