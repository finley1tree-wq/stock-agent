"""Strip API keys out of anything we print or log."""
import re
_PAT = re.compile(r"(apikey|api_key|token|key)=([^&\s]+)", re.I)

def redact(text) -> str:
    return _PAT.sub(lambda m: f"{m.group(1)}=***", str(text))
