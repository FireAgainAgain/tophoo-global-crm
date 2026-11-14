"""Retire phrase titles and split clearly paired English/Chinese legacy content."""
from datetime import datetime
from pathlib import Path
import json
import re
from sqlalchemy import inspect, text


def split_legacy_phrase(content):
    lines=[line.strip() for line in str(content or '').splitlines() if line.strip()]
    if len(lines)==2 and re.search(r'[A-Za-z]',lines[0]) and not re.search(r'[\u3400-\u9fff]',lines[0]) and re.search(r'[\u3400-\u9fff]',lines[1]):
        return lines[0],lines[1]
    return content or '', ''


def ensure_phrase_translation_schema(engine):
    table='crm_communication_phrases'
    if not inspect(engine).has_table(table):return
    with engine.begin() as connection:
        columns={col['name'] for col in inspect(connection).get_columns(table)}
        if 'translation' not in columns:
            connection.execute(text(f'ALTER TABLE {table} ADD COLUMN translation TEXT NULL'))
            connection.execute(text(f"UPDATE {table} SET translation='' WHERE translation IS NULL"))
            if engine.dialect.name=='mysql':
                connection.execute(text(f'ALTER TABLE {table} MODIFY translation TEXT NOT NULL'))
        if 'sort_order' not in columns:
            connection.execute(text(f'ALTER TABLE {table} ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0'))
            ordering='updated_at DESC, id DESC' if 'updated_at' in columns else 'id DESC'
            ids=connection.execute(text(f'SELECT id FROM {table} ORDER BY {ordering}')).scalars().all()
            for index,key in enumerate(ids):
                connection.execute(text(f'UPDATE {table} SET sort_order=:rank WHERE id=:id'),{'id':key,'rank':index})
        if 'title' not in columns:return
        rows=[dict(row) for row in connection.execute(text(f'SELECT * FROM {table}')).mappings()]
        if rows:
            folder=Path('backups')/('phrase-original-translation-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'before.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        for row in rows:
            if row.get('translation'):continue
            original,translation=split_legacy_phrase(row['content'])
            if translation:
                connection.execute(text(f'UPDATE {table} SET content=:content, translation=:translation WHERE id=:id'),{'id':row['id'],'content':original,'translation':translation})
        connection.execute(text(f'ALTER TABLE {table} DROP COLUMN title'))
