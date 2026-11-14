"""Add optional scenario assignment; existing phrases remain unassigned."""
from sqlalchemy import inspect, text
from app.models.communication_phrase import PhraseScene


def ensure_phrase_scene_schema(engine):
    PhraseScene.__table__.create(engine, checkfirst=True)
    if not inspect(engine).has_table('crm_communication_phrases'):
        return
    with engine.begin() as connection:
        columns = {c['name'] for c in inspect(connection).get_columns('crm_communication_phrases')}
        if 'scene_id' not in columns:
            reference = '' if engine.dialect.name == 'mysql' else ' REFERENCES crm_phrase_scenes(id)'
            connection.execute(text('ALTER TABLE crm_communication_phrases ADD COLUMN scene_id INTEGER NULL' + reference))
        indexes = {i['name'] for i in inspect(connection).get_indexes('crm_communication_phrases')}
        if 'ix_crm_communication_phrases_scene_id' not in indexes:
            connection.execute(text('CREATE INDEX ix_crm_communication_phrases_scene_id ON crm_communication_phrases (scene_id)'))
        if engine.dialect.name == 'mysql':
            inspector = inspect(connection)
            # Historical deployments use MyISAM, which ignores foreign keys.
            supports_foreign_keys = all(inspector.get_table_options(table).get('mysql_engine','').lower() == 'innodb'
                                        for table in ('crm_communication_phrases','crm_phrase_scenes'))
            foreign_keys = inspector.get_foreign_keys('crm_communication_phrases')
            if supports_foreign_keys and not any(key['constrained_columns'] == ['scene_id'] for key in foreign_keys):
                connection.execute(text('ALTER TABLE crm_communication_phrases ADD CONSTRAINT fk_crm_phrase_scene FOREIGN KEY (scene_id) REFERENCES crm_phrase_scenes(id)'))
