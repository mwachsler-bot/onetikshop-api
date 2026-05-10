"""
dedupe.py - Normalization and deduplication. No AI. Pure deterministic.
"""
import re
import hashlib

def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def normalize_product_name(name: str) -> str:
    if not name: return ""
    name = name.lower().strip()
    name = re.sub(r"[\u2122\u00ae\u00a9]", "", name)
    name = re.sub(r"\d+[\s-]?pack", "", name)
    colors = r"\b(black|white|grey|gray|red|blue|green|pink|purple|orange|yellow|brown|navy|beige|rose|gold|silver)\b"
    name = re.sub(colors, "", name)
    name = re.sub(r"\b(small|medium|large|xl|xxl|xs|mini|pro|plus|max|lite|ultra)\b", "", name)
    name = re.sub(r"\b[A-Z][a-z]+\b", "", name)
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def normalize_url(url: str) -> str:
    if not url: return ""
    url = url.lower().strip()
    url = re.sub(r"\?.*$", "", url)
    url = re.sub(r"#.*$", "", url)
    return url.rstrip("/")

def normalize_source(source: str) -> str:
    return re.sub(r"[^\w]", "_", source.lower().strip())

def create_dedupe_key(*parts: str) -> str:
    normalized = "|".join(normalize_text(str(p)) for p in parts if p)
    return hashlib.sha256(normalized.encode()).hexdigest()

def create_trend_dedupe_key(source: str, keyword: str, region: str = "US") -> str:
    return create_dedupe_key("trend", source, keyword, region)

def create_ad_dedupe_key(source: str, ad_id: str) -> str:
    return create_dedupe_key("ad", source, ad_id)

def create_hook_dedupe_key(hook_text: str, platform: str, niche: str = "") -> str:
    return create_dedupe_key("hook", hook_text[:150], platform, niche)

def create_product_dedupe_key(source: str, product_name: str) -> str:
    norm = normalize_product_name(product_name)
    return create_dedupe_key("product", source, norm)

HOOK_PATTERNS = [
    ("pattern_interrupt", r"why (your|you keep|does|are|do)|everyone is|nobody talks"),
    ("pain", r"\b(pain|hurt|struggle|tired|annoyed|frustrated|hate|stop|sick of|fed up)\b"),
    ("curiosity", r"\b(secret|nobody|they don.t want|hidden|truth about|what they)\b"),
    ("social_proof", r"\b(\d+ (day|week|month)|after using|results|transformation|before and after)\b"),
    ("comparison", r"\b(vs\.?|versus|compared|better than|instead of|switch from|upgrade from)\b"),
    ("urgency", r"\b(only|limited|last chance|today|expires|running out|sold out|hurry)\b"),
    ("pov", r"\b(pov:|when you|imagine|what if|picture this)\b"),
]
EMOTIONAL_PATTERNS = [
    ("shame", r"\b(embarrassed|ashamed|ugly|fat|old|weak|failing|broken|insecure)\b"),
    ("aspiration", r"\b(confident|proud|strong|beautiful|fit|amazing|love|achieve|goal)\b"),
    ("fear", r"\b(scared|worried|danger|risk|warning|careful|avoid|protect)\b"),
    ("humor", r"\b(funny|lol|haha|ridiculous|cannot believe|wild|wait for it)\b"),
    ("value", r"\b(save money|cheap|affordable|discount|deal|off|free)\b"),
]
OFFER_PATTERNS = [
    ("discount", r"\d+%?\s*off|discount|sale|deal|free shipping"),
    ("bundle", r"buy .{1,20} get|bogo|bundle|set of \d|pack of \d"),
    ("risk_reversal", r"free trial|try for free|no risk|money.?back|guarantee"),
]

def classify_hook(text: str) -> dict:
    lower = text.lower()
    hook_type = "generic"
    for htype, pattern in HOOK_PATTERNS:
        if re.search(pattern, lower):
            hook_type = htype
            break
    emotional_angle = "neutral"
    for angle, pattern in EMOTIONAL_PATTERNS:
        if re.search(pattern, lower):
            emotional_angle = angle
            break
    offer_type = None
    for otype, pattern in OFFER_PATTERNS:
        if re.search(pattern, lower):
            offer_type = otype
            break
    return {"hook_type": hook_type, "emotional_angle": emotional_angle, "offer_type": offer_type}

def extract_hook_from_text(text: str, max_chars: int = 150) -> str:
    if not text: return ""
    text = text.strip()
    for sep in ["!", "?", ".", "\n"]:
        idx = text.find(sep)
        if 0 < idx < max_chars:
            return text[:idx + 1].strip()
    return text[:max_chars].strip()
