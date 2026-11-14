"""Pydantic schemas for accounts, workspaces and projects."""

from app.core.modules import MODULE_CATALOG
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^1\d{10}$")
    wechat_id: str | None = Field(default=None, max_length=100)
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^1\d{10}$")
    wechat_id: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    plan_code: str = Field(default="free", min_length=1, max_length=50)


class AdminUserPasswordRequest(BaseModel):
    model_config = {"extra": "forbid"}
    new_password: str = Field(min_length=8, max_length=128, repr=False)

    @field_validator('new_password')
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('密码不能全部为空格')
        return value


class AdminUpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^1\d{10}$")
    wechat_id: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    plan_code: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator('display_name', mode='before')
    @classmethod
    def trim_display_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def require_profile_values(self):
        for field in ('email', 'display_name'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} 不能为空')
        return self


class AdminPlanUpdateRequest(BaseModel):
    code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,48}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    monthly_price: float = Field(ge=0, le=999999)
    currency: str = Field(pattern=r"^(USD|CNY)$")
    project_limit: int = Field(ge=1, le=10000)
    module_keys: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_upgrade_available: bool = False


class AdminPlanCreateRequest(AdminPlanUpdateRequest):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,48}$")


class TestCheckoutComplete(BaseModel):
    plan_code: str = Field(default="professional", min_length=1, max_length=50)
    payment_method: str = Field(pattern=r"^(stripe|alipay)$")


class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class SiteProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    site_url: str = Field(min_length=1, max_length=500)


class SiteProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    site_url: str | None = Field(default=None, min_length=1, max_length=500)


class SiteProjectMoveRequest(BaseModel):
    direction: str = Field(pattern=r"^(up|down)$")


class SiteProjectDeleteRequest(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=150)


class ProjectLinkRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=1, max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("网址名称不能为空")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("网址必须以 http:// 或 https:// 开头")
        return value


class ProjectLinkMoveRequest(BaseModel):
    direction: str = Field(pattern=r"^(up|down)$")


class WorkspaceMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class ProjectMemberRequest(BaseModel):
    user_id: int | None = Field(default=None, gt=0)
    email: EmailStr | None = None
    role: str = Field(default="sales", pattern=r"^(top_admin|sales|custom)$")
    permissions: list[str] = Field(default_factory=list, max_length=len(MODULE_CATALOG))
    write_permissions: list[str] | None = Field(default=None, max_length=len(MODULE_CATALOG))
    project_role_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_user(self):
        if self.user_id is None and self.email is None:
            raise ValueError("请输入要加入项目的用户邮箱。")
        return self


class ProjectMemberRoleRequest(BaseModel):
    role: str = Field(pattern=r"^(top_admin|sales|custom)$")
    permissions: list[str] = Field(default_factory=list, max_length=len(MODULE_CATALOG))
    write_permissions: list[str] | None = Field(default=None, max_length=len(MODULE_CATALOG))
    project_role_id: int | None = Field(default=None, gt=0)


class ProjectRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    permissions: list[str] = Field(default_factory=list, max_length=len(MODULE_CATALOG))
    write_permissions: list[str] | None = Field(default=None, max_length=len(MODULE_CATALOG))
