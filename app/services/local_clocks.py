"""Shared customer local-clock metadata for lists; no business data is changed."""
from sqlalchemy import select


def add_local_clocks(items, rows, project_id, db, kind):
    from app.models.communication import CommunicationSetting
    from app.schemas.communication import PlaceConfig
    from app.services.communication import infer_place, places_by_key, country_code
    target_id = CommunicationSetting.lead_id if kind == 'leads' else CommunicationSetting.customer_id
    stored = {getattr(setting, 'lead_id' if kind == 'leads' else 'customer_id'): PlaceConfig.model_validate_json(setting.settings_json)
              for setting in db.scalars(select(CommunicationSetting).where(
                  CommunicationSetting.site_project_id == project_id,
                  target_id.in_([item.id for item in items if item]),
                  CommunicationSetting.target_key.in_([f'{kind}:{item.id}' for item in items if item])))} if items else {}
    for item, row in zip(items, rows):
        config = stored.get(item.id) if item else None
        country = item.country if item else row.get("contact_country", "")
        address = item.company_address if item else row.get("company_address", "")
        place = places_by_key().get(config.country + ':' + config.timezone) if config else infer_place(country, address)[0]
        row['local_clock'] = {'timezone': place['timezone'], 'city': (config.city or place['city']) if config else place['city']} if place else {
            'timezone': None, 'hint': '待确认时区' if country_code(country) else '待补充地区'}

