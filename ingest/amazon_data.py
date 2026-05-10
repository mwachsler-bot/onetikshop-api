"""
ingest/amazon_data.py - Amazon PA-API 5.0 product data ingestion.
Requires AWS_ACCESS_KEY, AWS_SECRET_KEY, AMAZON_PARTNER_TAG env vars.
Returns placeholder if not configured.
"""
import os, logging, time, json
from datetime import datetime, timezone
import httpx
from dedupe import create_product_dedupe_key, normalize_product_name

log = logging.getLogger(__name__)
AMAZON_HOST = "webservices.amazon.com"
AMAZON_ENDPOINT = f"https://{AMAZON_HOST}/paapi5/searchitems"

def run_amazon_ingestion(keywords, niche=None):
    aws_key = os.getenv("AWS_ACCESS_KEY")
    aws_secret = os.getenv("AWS_SECRET_KEY")
    partner_tag = os.getenv("AMAZON_PARTNER_TAG")
    if not all([aws_key, aws_secret, partner_tag]):
        log.info("Amazon PA-API credentials not configured. Set AWS_ACCESS_KEY, AWS_SECRET_KEY, AMAZON_PARTNER_TAG in .env.")
        return {"product_market_data": [], "_placeholder": True, "_message": "Amazon PA-API not configured. Join Amazon Associates to activate."}
    products_out = []
    headers = {"Content-Type": "application/json; charset=utf-8", "X-Amz-Target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems", "Host": AMAZON_HOST}
    with httpx.Client(timeout=30) as client:
        for keyword in keywords:
            log.info(f"Amazon PA-API: {keyword}")
            time.sleep(1.0)
            payload = {"Keywords": keyword, "Resources": ["ItemInfo.Title", "Offers.Listings.Price", "CustomerReviews.Count", "CustomerReviews.StarRating", "Images.Primary.Medium"], "SearchIndex": "All", "ItemCount": 10, "PartnerTag": partner_tag, "PartnerType": "Associates", "Marketplace": "www.amazon.com"}
            try:
                r = client.post(AMAZON_ENDPOINT, json=payload, headers=headers)
                r.raise_for_status()
                for item in r.json().get("SearchResult", {}).get("Items", []):
                    asin = item.get("ASIN", "")
                    title = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
                    price_data = item.get("Offers", {}).get("Listings", [{}])[0].get("Price", {})
                    retail_price = price_data.get("Amount")
                    reviews = item.get("CustomerReviews", {})
                    review_count = reviews.get("Count")
                    rating = reviews.get("StarRating", {}).get("Value")
                    image_url = item.get("Images", {}).get("Primary", {}).get("Medium", {}).get("URL")
                    norm_name = normalize_product_name(title)
                    products_out.append({
                        "source": "amazon_paapi", "niche": niche, "product_name": title,
                        "normalized_product_name": norm_name or normalize_product_name(keyword),
                        "category": niche, "product_url": f"https://www.amazon.com/dp/{asin}",
                        "image_url": image_url,
                        "retail_price": float(retail_price) if retail_price else None,
                        "rating": float(rating) if rating else None,
                        "review_count": int(review_count) if review_count else 0,
                        "raw_data": {"asin": asin},
                        "dedupe_key": create_product_dedupe_key("amazon_paapi", asin or title),
                    })
                    log.info(f"  Amazon: {title[:50]} ${retail_price} {rating}*")
            except Exception as e:
                log.error(f"Amazon error for {keyword}: {e}")
    log.info(f"Amazon: {len(products_out)} products.")
    return {"product_market_data": products_out}
