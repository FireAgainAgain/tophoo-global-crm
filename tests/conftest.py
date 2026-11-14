"""Keep the test suite independent of local credentials and databases."""

import os
from secrets import token_hex


os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = token_hex(32)
os.environ["MAIL_ENCRYPTION_KEY"] = ""
