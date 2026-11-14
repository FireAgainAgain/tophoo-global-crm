"""Database models for the standalone Tophoo CRM application."""

from app.models.base import Base
from app.models.user_link import UserLink, UserLinkCategory, UserLinkMigration
from app.models.identity import ProjectLink, ProjectMember, ProjectRole, RevokedAccessToken, SiteProject, User, Workspace, WorkspaceMember
from app.models.billing import Plan, Subscription
from app.models.customer import Company, Customer, CustomerPerson, CustomerPoolAudit, Lead, ProjectCompany, ProjectContact, ProspectingCandidate, ProspectingEntry, ProspectingJob
from app.models.contact_record import ContactRecord
from app.models.communication_script import CommunicationScript, CommunicationScriptCategory
from app.models.rfq import Rfq, RfqTemplate
from app.models.competitor import Competitor, CompetitorKeyword, CompetitorWebsite
from app.models.ai_config import AiConfiguration, AiFeatureBinding, AiModelConfiguration
from app.models.acquisition import AcquisitionConnection, AcquisitionConnectionTest
from app.models.keyword import Keyword, KeywordCategory, KeywordCategoryMap, KeywordImport

__all__ = ["Base", "UserLink", "UserLinkCategory", "UserLinkMigration", "AcquisitionConnection", "AcquisitionConnectionTest", "ProjectLink", "ProjectMember", "ProjectRole", "RevokedAccessToken", "SiteProject", "User", "Workspace", "WorkspaceMember", "Plan", "Subscription", "Company", "Customer", "CustomerPerson", "CustomerPoolAudit", "ProjectCompany", "ProjectContact", "ProspectingEntry", "Lead", "ContactRecord", "CommunicationScript", "CommunicationScriptCategory", "Rfq", "RfqTemplate", "Competitor", "CompetitorWebsite", "CompetitorKeyword"]

from app.models.follow_up import FollowUpPlan


from app.models.lead_development import LeadInteraction, LeadConversionHistory, LeadOutreachDraft
from app.models.lead_contact_scan import LeadContactScan

from app.models.mic_product import MicProduct, MicProductImage

from app.models.communication import CommunicationPreference, CommunicationSetting


from app.models.mail import MailConfiguration, MailDelivery, MailAccount

from app.models.communication_phrase import PhraseCategory, PhraseScene, CommunicationPhrase

from app.models.quotation import Quotation, QuotationTemplate
from app.models.sales_contract import SalesContract, SignedContractFile

