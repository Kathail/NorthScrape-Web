from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# --- CONFIGURATION ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
]

CATEGORIES = [
    "Convenience Stores", "Grocery Stores", "Gas Stations", "Gift Shops", "Pharmacies",
    "Candy Stores", "General Stores", "Variety Stores", "Trading Posts", "Tourist Attractions",
    "Sports Complexes", "Sports Venues", "Museums", "Art Galleries", "Bookstores",
    "Music Stores", "Sports Stores", "Electronics Stores", "Fashion Stores", "Pet Stores",
]

NORTHERN_LOCATIONS = sorted([
    "Sudbury, ON", "North Bay, ON", "Sault Ste. Marie, ON", "Timmins, ON", "Thunder Bay, ON",
    "Elliot Lake, ON", "Temiskaming Shores, ON", "Kenora, ON", "Dryden, ON", "Fort Frances, ON",
    "Kapuskasing, ON", "Kirkland Lake, ON", "Espanola, ON", "Blind River, ON", "Cochrane, ON",
    "Hearst, ON", "Iroquois Falls, ON", "Marathon, ON", "Wawa, ON", "Little Current, ON",
    "Sioux Lookout, ON", "Red Lake, ON", "Chapleau, ON", "Nipigon, ON", "Parry Sound, ON",
    "Sturgeon Falls, ON", "Manitouwadge, ON", "Gogama, ON", "Foleyet, ON", "Britt, ON",
])

# --- UTILITIES (Ported from Original) ---

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

class DataCleaner:
    @staticmethod
    def clean_phone(phone_str):
        if not phone_str or phone_str.lower() in ["n/a", ""]: return "N/A"
        digits = re.sub(r"\D", "", phone_str)
        if len(digits) == 10: return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        if len(digits) == 11 and digits.startswith("1"): return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return "N/A"

    @staticmethod
    def fix_address(address):
        if not address or address == "N/A": return "N/A"
        addr = re.sub(r"(ON|On|Ontario)([A-Za-z]\d[A-Za-z])", r"\1 \2", address, flags=re.IGNORECASE)
        parts = [p.strip() for p in addr.split(",")]
        unique_parts = []
        seen_lower = set()
        for p in parts:
            if not p: continue
            if re.match(r"^(on|ontario)$", p, flags=re.IGNORECASE): p = "ON"
            p_clean = re.sub(r"\s+District$", "", p, flags=re.IGNORECASE)
            p_lower = p_clean.lower()
            if p_lower not in seen_lower:
                unique_parts.append(p_clean.title() if p_clean != "ON" else "ON")
                seen_lower.add(p_lower)
        addr = ", ".join(unique_parts)
        addr = re.sub(r"([A-Za-z]\d[A-Za-z])\s?(\d[A-Za-z]\d)", lambda m: f"{m.group(1).upper()} {m.group(2).upper()}", addr)
        return addr

class ScraperEngine:
    @staticmethod
    def search_yp_enrich(name, address):
        match = re.search(r"([^,]+),\s*(ON|Ontario)", address, flags=re.IGNORECASE)
        loc = match.group(1).strip() if match else "ON"
        url = f"https://www.yellowpages.ca/search/si/1/{name.replace(' ', '+')}/{loc.replace(' ', '+')}"
        try:
            res = requests.get(url, headers=get_headers(), timeout=5)
            if res.status_code != 200: return None
            soup = BeautifulSoup(res.text, "html.parser")
            listing = soup.find("div", class_="listing__content__wrapper")
            if not listing: return None
            
            phone_tag = listing.find("h4", class_="impl_phone_number") or listing.find("li", class_="mlr__item--phone")
            phone = phone_tag.get_text(strip=True) if phone_tag else "N/A"
            
            website = "N/A"
            website_item = listing.find("li", class_="mlr__item--website")
            if website_item:
                link_tag = website_item.find("a")
                href = link_tag.get("href") if link_tag else None
                if href:
                    website = f"https://www.yellowpages.ca{href}"
                    if "redirect=" in website:
                        parsed = urlparse(website)
                        query_params = parse_qs(parsed.query)
                        if query_params.get("redirect"): website = query_params.get("redirect")[0]
            return {"phone": DataCleaner.clean_phone(phone), "website": website}
        except: return None

    @staticmethod
    def search_ddg(name, address):
        match = re.search(r"([^,]+),\s*(ON|Ontario)", address, flags=re.IGNORECASE)
        city = match.group(1).strip() if match else ""
        try:
            res = requests.post("https://html.duckduckgo.com/html/", data={"q": f"{name} {city} phone"}, headers=get_headers(), timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            text = soup.get_text()
            phones = re.findall(r"(?:\+?1[-. ]?)?\(?([2-9][0-9]{2})\)?[-. ]?([2-9][0-9]{2})[-. ]?([0-9]{4})", text)
            phone = f"({phones[0][0]}) {phones[0][1]}-{phones[0][2]}" if phones else "N/A"
            
            website = "N/A"
            for link in soup.find_all("a", class_="result__a"):
                href = link.get("href")
                if href and "duckduckgo" not in href and not any(x in href for x in ["yelp", "yellowpages", "411.ca"]):
                    website = href
                    break
            return {"phone": phone, "website": website}
        except: return {"phone": "N/A", "website": "N/A"}

    @staticmethod
    def generate_yp_list(keyword, location):
        url = f"https://www.yellowpages.ca/search/si/1/{keyword.replace(' ', '+')}/{location.replace(' ', '+')}"
        results = []
        try:
            resp = requests.get(url, headers=get_headers(), timeout=8)
            soup = BeautifulSoup(resp.text, "html.parser")
            for listing in soup.find_all("div", class_="listing__content__wrapper"):
                name_tag = listing.find("a", class_="listing__name--link")
                addr_tag = listing.find("span", class_="listing__address--full")
                if name_tag and addr_tag:
                    results.append({"Name": name_tag.get_text(strip=True), "Address": addr_tag.get_text(strip=True)})
            return results
        except: return []

# --- FLASK ROUTES ---

@app.route('/northscrape')
def index():
    return render_template('index.html', categories=CATEGORIES, locations=NORTHERN_LOCATIONS)

@app.route('/northscrape/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/northscrape/api/scrape', methods=['POST'])
def scrape_api():
    """
    Handles Generation + Enrichment in one go.
    Receives JSON: { "categories": [], "locations": [] }
    """
    data = request.json
    cats = data.get('categories', [])
    locs = data.get('locations', [])
    
    # 1. Generate Leads
    raw_leads = []
    seen = set()
    
    # Use ThreadPool for initial generation
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for c in cats:
            for l in locs:
                futures.append(executor.submit(ScraperEngine.generate_yp_list, c, l))
        
        for f in as_completed(futures):
            res = f.result()
            for r in res:
                clean_addr = DataCleaner.fix_address(r['Address'])
                key = f"{r['Name']}|{clean_addr[:10]}"
                if key not in seen:
                    seen.add(key)
                    raw_leads.append({
                        "Name": r['Name'],
                        "Address": clean_addr,
                        "Phone": "N/A",
                        "Website": "N/A"
                    })

    # 2. Enrich Leads (Phone/Web)
    final_data = []
    
    def enrich_row(row):
        # Try YP
        enriched = ScraperEngine.search_yp_enrich(row['Name'], row['Address'])
        if not enriched or enriched['phone'] == "N/A":
            # Fallback DDG
            enriched = ScraperEngine.search_ddg(row['Name'], row['Address'])
        
        row['Phone'] = enriched.get('phone', 'N/A')
        row['Website'] = enriched.get('website', 'N/A')
        return row

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(enrich_row, row) for row in raw_leads]
        for f in as_completed(futures):
            final_data.append(f.result())

    return jsonify(final_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
