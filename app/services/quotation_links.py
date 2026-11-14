"""Resolve current buyer/contact facts without mutating stored quotation content."""
from sqlalchemy import select
from app.models import Customer, ProjectContact
from app.services.customer_people import people_for


def live_document(db, project_id, owner_id, document, customer_id, cache=None):
    result = dict(document)
    if not customer_id:
        return result
    cached = cache.get(customer_id) if cache is not None else None
    if cached is None:
        query = select(Customer).join(ProjectContact, ProjectContact.contact_id == Customer.id).where(
            Customer.id == customer_id, ProjectContact.site_project_id == project_id)
        if owner_id is not None:
            query = query.where(ProjectContact.owner_user_id == owner_id)
        customer = db.scalar(query)
        people = people_for(db, customer.id) if customer else []
        if cache is not None:
            cache[customer_id] = (customer, people)
    else:
        customer, people = cached
    if not customer:
        return result
    person = next((p for p in people if p.id == result.get('contact_person_id')), None)
    if person is None and not result.get('contact_person_id'):
        matches = [p for p in people if (result.get('buyer_email') and (p.email or '').casefold() == result['buyer_email'].casefold())
                   or (result.get('attention') and (p.contact_name or '').casefold() == result['attention'].casefold())]
        if len(matches) == 1:
            person = matches[0]
    if person is None:
        person = next((p for p in people if p.primary_slot == 1), people[0] if people else None)
    result.update(buyer_company=customer.company or customer.name, buyer_address=customer.company_address or '',
        contact_person_id=person.id if person else None,
        attention=(person.contact_name or '') if person else ('' if customer.people_initialized else customer.name or ''),
        buyer_email=(person.email or '') if person else ('' if customer.people_initialized else customer.email or ''),
        buyer_phone=(person.phone or person.whatsapp or '') if person else ('' if customer.people_initialized else customer.phone or customer.whatsapp or ''))
    return result
