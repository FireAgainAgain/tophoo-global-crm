"""Conversion retention shares the caller transaction, without overwriting customer facts."""
import json
from sqlalchemy import select, delete, inspect, text, update
from app.models import ContactRecord, LeadInteraction, LeadConversionHistory, LeadOutreachDraft
from app.services.workflow_people import workflow_people

def ensure_lead_development_date_schema(engine):
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("crm_leads")}
        if "development_date" not in columns:
            connection.execute(text("ALTER TABLE crm_leads ADD COLUMN development_date DATE NULL"))


def remove_lead_development(db,ids):
    from app.models import LeadContactScan
    db.execute(delete(LeadContactScan).where(LeadContactScan.lead_id.in_(ids)))
    from app.models.mail import MailDelivery
    db.execute(update(MailDelivery).where(MailDelivery.lead_id.in_(ids)).values(lead_id=None))
    from app.models.communication import CommunicationSetting
    db.execute(delete(CommunicationSetting).where(CommunicationSetting.lead_id.in_(ids)))
    db.execute(delete(LeadOutreachDraft).where(LeadOutreachDraft.lead_id.in_(ids)))
    db.execute(delete(LeadInteraction).where(LeadInteraction.lead_id.in_(ids)))

def retain_conversion(db,project,lead,customer,actor_id,mode):
    interactions=db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id==lead.id).order_by(LeadInteraction.occurred_at,LeadInteraction.id)).all()
    snapshot={column.name:(value.isoformat() if hasattr(value,'isoformat') else value) for column in lead.__table__.columns if (value:=getattr(lead,column.name)) is not None}
    snapshot['contacts']=workflow_people(lead)
    # Keep the mail-to-lead association before conversion detaches the deleted lead.
    # Delivery logs stay separate from manually maintained contact records.
    from app.models.mail import MailDelivery
    from app.services.lead_outreach_stats import outreach_stats
    deliveries=db.scalars(select(MailDelivery).where(MailDelivery.site_project_id==project.id,MailDelivery.lead_id==lead.id).order_by(MailDelivery.id)).all()
    if deliveries:
        snapshot['outreach_stats']=outreach_stats(db,project.id,lead.id)
        snapshot['outreach_deliveries']=[{'id':row.id,'recipient':row.recipient,'status':row.status,
            'accepted_at':row.accepted_at.isoformat() if row.accepted_at else None} for row in deliveries]
    from app.models.communication import CommunicationSetting
    communication=db.scalars(select(CommunicationSetting).where(CommunicationSetting.site_project_id==project.id,CommunicationSetting.lead_id==lead.id)).all()
    if communication:snapshot['communication_settings']=[{'target_key':row.target_key,'config':json.loads(row.settings_json)} for row in communication]
    draft=db.get(LeadOutreachDraft,lead.id)
    if draft and (draft.subject or draft.content or draft.content_translation or draft.recipient_name or draft.recipient_email or draft.content_html):
        snapshot['outreach_draft']={'content':draft.content,'content_translation':draft.content_translation}
        if draft.subject:snapshot['outreach_draft']['subject']=draft.subject
        for key in ('recipient_name','recipient_email','content_html'):
            if getattr(draft,key):snapshot['outreach_draft'][key]=getattr(draft,key)
    snapshot['interactions']=[{key:(value.isoformat() if hasattr(value,'isoformat') else value) for key in ('id','occurred_at','direction','contact_name','channel','subject','content','content_translation','created_by_user_id','created_at','updated_at','source_outreach_json','content_html') if (value:=getattr(record,key)) is not None} for record in interactions]
    db.add(LeadConversionHistory(site_project_id=project.id,customer_id=customer.id,source_lead_id=lead.id,converted_by_user_id=actor_id,mode=mode,snapshot_json=json.dumps(snapshot,ensure_ascii=False)))
    from app.services.followup_note import NOTE_CHANNEL, followup_rows, note_data, write_note
    merged = None
    if any(record.channel == NOTE_CHANNEL for record in interactions):
        customer_rows = followup_rows(db, project.id, customer.id, lock=True)
        merged = '\n\n'.join(filter(None, (
            note_data(customer_rows)['content'],
            note_data(sorted(interactions, key=lambda record: record.id))['content'],
        )))
    for record in interactions:
        if record.channel == NOTE_CHANNEL:
            continue
        db.add(ContactRecord(site_project_id=project.id,contact_id=customer.id,created_by_user_id=record.created_by_user_id,
            occurred_at=record.occurred_at,direction=record.direction,contact_name=record.contact_name,channel=record.channel,
            subject=record.subject,content=record.content,content_translation=record.content_translation,content_html=record.content_html,source_outreach_json=record.source_outreach_json,
            created_at=record.created_at,updated_at=record.updated_at))
    if merged is not None:
        db.flush()
        rows = followup_rows(db, project.id, customer.id, lock=True)
        write_note(db, rows, project.id, customer.id, merged, actor_id)
    from app.services.communication import transfer_settings
    transfer_settings(db,project.id,lead,customer)
    remove_lead_development(db,[lead.id])


def add_html_column(connection,table,dialect):
    if dialect=="mysql":
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN content_html LONGTEXT NULL"))
        connection.execute(text(f"UPDATE {table} SET content_html='' WHERE content_html IS NULL"))
        connection.execute(text(f"ALTER TABLE {table} MODIFY COLUMN content_html LONGTEXT NOT NULL"))
    else:connection.execute(text(f"ALTER TABLE {table} ADD COLUMN content_html TEXT NOT NULL DEFAULT ''"))


def ensure_lead_development_schema(engine):
    for model in (LeadInteraction,LeadConversionHistory,LeadOutreachDraft):model.__table__.create(engine,checkfirst=True)
    with engine.begin() as connection:
        if 'subject' not in {item['name'] for item in inspect(connection).get_columns('crm_lead_outreach_drafts')}:
            connection.execute(text("ALTER TABLE crm_lead_outreach_drafts ADD COLUMN subject VARCHAR(260) NOT NULL DEFAULT ''"))
        draft_columns={item['name'] for item in inspect(connection).get_columns('crm_lead_outreach_drafts')}
        for name,size in (('recipient_name',160),('recipient_email',260)):
            if name not in draft_columns:connection.execute(text(f"ALTER TABLE crm_lead_outreach_drafts ADD COLUMN {name} VARCHAR({size}) NOT NULL DEFAULT ''"))
        for table in ('crm_lead_outreach_drafts','user_mail_deliveries'):
            if inspect(connection).has_table(table) and 'content_html' not in {c['name'] for c in inspect(connection).get_columns(table)}:
                if engine.dialect.name=='mysql':
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN content_html LONGTEXT NULL'))
                    connection.execute(text(f"UPDATE {table} SET content_html='' WHERE content_html IS NULL"))
                    connection.execute(text(f'ALTER TABLE {table} MODIFY COLUMN content_html LONGTEXT NOT NULL'))
                else:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN content_html TEXT NOT NULL DEFAULT ''"))
        for table in ('crm_lead_interactions','crm_contact_records'):
            if inspect(connection).has_table(table) and 'source_outreach_json' not in {c['name'] for c in inspect(connection).get_columns(table)}:
                kind='LONGTEXT' if engine.dialect.name=='mysql' else 'TEXT'
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN source_outreach_json {kind} NULL'))
            if inspect(connection).has_table(table) and 'content_html' not in {c['name'] for c in inspect(connection).get_columns(table)}:
                kind='LONGTEXT' if engine.dialect.name=='mysql' else 'TEXT'
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN content_html {kind} NULL'))
        columns={item['name'] for item in inspect(connection).get_columns('crm_lead_interactions')}
        if 'content_translation' not in columns:connection.execute(text('ALTER TABLE crm_lead_interactions ADD COLUMN content_translation TEXT NULL'))
        if 'updated_at' not in columns:
            connection.execute(text('ALTER TABLE crm_lead_interactions ADD COLUMN updated_at DATETIME NULL'))
            connection.execute(text('UPDATE crm_lead_interactions SET updated_at=created_at WHERE updated_at IS NULL'))
    if engine.dialect.name=='mysql':
        with engine.begin() as connection:
            if not str(next(c['type'] for c in inspect(connection).get_columns('crm_lead_interactions') if c['name']=='occurred_at')).upper().startswith('DATETIME'):
                connection.execute(text('ALTER TABLE crm_lead_interactions MODIFY COLUMN occurred_at DATETIME NOT NULL'))
            for table,column in (('crm_lead_outreach_drafts','content_html'),('user_mail_deliveries','content_html'),('user_mail_configurations','signature'),('crm_lead_conversion_history','snapshot_json'),('crm_lead_interactions','content'),('crm_lead_interactions','content_translation'),('crm_contact_records','content'),('crm_contact_records','content_translation')):
                columns={item['name']:item['type'] for item in inspect(connection).get_columns(table)}
                if not str(columns[column]).upper().startswith('LONGTEXT'):
                    nullable=' NULL' if column=='content_translation' else ' NOT NULL'
                    connection.execute(text(f'ALTER TABLE {table} MODIFY COLUMN {column} LONGTEXT{nullable}'))


def retire_lead_followup_data(engine):
    with engine.begin() as connection:
        if 'crm_lead_development' in inspect(connection).get_table_names():
            connection.execute(text('DROP TABLE crm_lead_development'))
        if 'crm_lead_conversion_history' in inspect(connection).get_table_names():
            for row in connection.execute(text('SELECT id,snapshot_json FROM crm_lead_conversion_history')).mappings():
                value=json.loads(row['snapshot_json'])
                if 'development' in value:
                    value.pop('development')
                    connection.execute(text('UPDATE crm_lead_conversion_history SET snapshot_json=:snapshot WHERE id=:id'),{'snapshot':json.dumps(value,ensure_ascii=False),'id':row['id']})
