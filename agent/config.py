import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

PIPEDRIVE_API_TOKEN = os.environ["PIPEDRIVE_API_TOKEN"]
PIPEDRIVE_COMPANY_DOMAIN = os.environ["PIPEDRIVE_COMPANY_DOMAIN"]
PIPEDRIVE_BASE_URL = f"https://{PIPEDRIVE_COMPANY_DOMAIN}.pipedrive.com/api/v1"

READAI_API_KEY = os.environ["READAI_API_KEY"]
READAI_BASE_URL = "https://api.read.ai/api/v1"

AZURE_CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
AZURE_CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
AZURE_TENANT_ID = os.environ["AZURE_TENANT_ID"]
SHAREPOINT_SITE_ID = os.environ["SHAREPOINT_SITE_ID"]
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
