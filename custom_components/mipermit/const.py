"""Constants for the MiPermit integration."""

DOMAIN = "mipermit"

SERVICE_GET_PERMITS = "get_permits"
SERVICE_ACTIVATE_PERMIT = "activate_permit"

# Config entry keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CDP_URL = "cdp_url"

# Default CDP WebSocket URL for the alexbelgium Browserless Chrome add-on
DEFAULT_CDP_URL = "ws://homeassistant:3000"

URL_LOGIN = "https://secure.mipermit.com/root/Application/Login.aspx"
URL_ACCOUNT = "https://secure.mipermit.com/root/Account/AccountManagement.aspx"
URL_VISITORS = "https://secure.mipermit.com/root/Account/VisitorsManagement.aspx"
