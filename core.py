import random
import re
import time
from typing import List, Dict
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

# --- Configuration & Constants ---

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
]

CATEGORIES = [
    "Convenience Stores",
    "Grocery Stores",
    "Gas Stations",
    "Gift Shops",
    "Pharmacies",
    "Candy Stores",
    "General Stores",
    "Variety Stores",
    "Trading Posts",
    "Tourist Attractions",
    "Sports Complexes",
    "Sports Venues",
    "Museums",
    "Art Galleries",
    "Bookstores",
    "Music Stores",
    "Sports Stores",
    "Electronics Stores",
    "Fashion Stores",
    "Pet Stores",
]

POSTAL_MAP = {
    "P0A": "Parry Sound",
    "P0B": "Muskoka",
    "P0C": "Mactier",
    "P0E": "Manitoulin",
    "P0G": "Parry Sound",
    "P0H": "Nipissing",
    "P0J": "Timiskaming",
    "P0K": "Cochrane",
    "P0L": "Hearst",
    "P0M": "Sudbury",
    "P0N": "Cochrane",
    "P0P": "Manitoulin",
    "P0R": "Algoma",
    "P0S": "Algoma",
    "P0T": "Nipigon",
    "P0V": "Red Lake",
    "P0W": "Rainy River",
    "P1A": "North Bay",
    "P1B": "North Bay",
    "P1C": "North Bay",
    "P1H": "Huntsville",
    "P2A": "Parry Sound",
    "P2B": "Sturgeon Falls",
    "P2N": "Kirkland Lake",
    "P3A": "Sudbury",
    "P3B": "Sudbury",
    "P3C": "Sudbury",
    "P3E": "Sudbury",
    "P3G": "Sudbury",
    "P3L": "Garson",
    "P3N": "Val Caron",
    "P3P": "Hanmer",
    "P3Y": "Lively",
    "P4N": "Timmins",
    "P4P": "Timmins",
    "P4R": "Timmins",
    "P5A": "Elliot Lake",
    "P5E": "Espanola",
    "P5N": "Kapuskasing",
    "P6A": "Sault Ste. Marie",
    "P6B": "Sault Ste. Marie",
    "P6C": "Sault Ste. Marie",
    "P7A": "Thunder Bay",
    "P7B": "Thunder Bay",
    "P7C": "Thunder Bay",
    "P7E": "Thunder Bay",
    "P8N": "Dryden",
    "P8T": "Sioux Lookout",
    "P9A": "Fort Frances",
    "P9N": "Kenora",
    "K0M": "Central Ontario",
}

NORTHERN_LOCATIONS = sorted(
    [
        "Sudbury, ON",
        "North Bay, ON",
        "Sault Ste. Marie, ON",
        "Timmins, ON",
        "Thunder Bay, ON",
        "Elliot Lake, ON",
        "Temiskaming Shores, ON",
        "Kenora, ON",
        "Dryden, ON",
        "Fort Frances, ON",
        "Kapuskasing, ON",
        "Kirkland Lake, ON",
        "Espanola, ON",
        "Blind River, ON",
        "Cochrane, ON",
        "Hearst, ON",
        "Iroquois Falls, ON",
        "Marathon, ON",
        "Wawa, ON",
        "Little Current, ON",
        "Sioux Lookout, ON",
        "Red Lake, ON",
        "Chapleau, ON",
        "Nipigon, ON",
        "Parry Sound, ON",
        "Sturgeon Falls, ON",
        "Manitouwadge, ON",
        "Gogama, ON",
        "Foleyet, ON",
        "Britt, ON",
    ]
)


def get_headers() -> Dict[str, str]:
    """Returns headers with random User-Agent."""
    return {"User-Agent": random.choice(USER_AGENTS)}


class DataCleaner:
    """Static utility class for standardizing data formats."""

    @staticmethod
    def clean_phone(phone_str: str) -> str:
        """Normalizes phone numbers to (XXX) XXX-XXXX format."""
        if not phone_str or phone_str.lower() in ["n/a", ""]:
            return "N/A"

        digits = re.sub(r"\D", "", phone_str)

        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return "N/A"

    @staticmethod
    def fix_address(address: str) -> str:
        """Standardizes address strings and infers missing cities based on Postal Code FSA."""
        if not address or address == "N/A":
            return "N/A"

        addr = re.sub(
            r"(ON|On|Ontario)([A-Za-z]\d[A-Za-z])",
            r"\1 \2",
            address,
            flags=re.IGNORECASE,
        )

        parts = [p.strip() for p in addr.split(",")]
        unique_parts = []
        seen_lower = set()
        for p in parts:
            if not p:
                continue
            if re.match(r"^(on|ontario)$", p, flags=re.IGNORECASE):
                p = "ON"
            p_clean = re.sub(r"\s+District$", "", p, flags=re.IGNORECASE)
            p_lower = p_clean.lower()
            if p_lower not in seen_lower:
                unique_parts.append(p_clean.title() if p_clean != "ON" else "ON")
                seen_lower.add(p_lower)

        addr = ", ".join(unique_parts)

        addr = re.sub(
            r"([A-Za-z]\d[A-Za-z])\s?(\d[A-Za-z]\d)",
            lambda m: f"{m.group(1).upper()} {m.group(2).upper()}",
            addr,
        )

        postal_match = re.search(r"([A-Za-z]\d[A-Za-z])\s?(\d[A-Za-z]\d)", addr)
        if postal_match:
            fsa = postal_match.group(1).upper()
            if re.search(
                rf",\s*(ON|On|Ontario)\s*{re.escape(fsa)}", addr, flags=re.IGNORECASE
            ):
                inferred_city = POSTAL_MAP.get(fsa, "Northern Ontario")
                inferred_core = re.sub(
                    r"\s+District$", "", inferred_city, flags=re.IGNORECASE
                )
                is_present = any(
                    inferred_core.lower() in part.lower() for part in unique_parts
                )
                if not is_present:
                    addr = re.sub(
                        r",\s*(ON|On|Ontario)",
                        f", {inferred_city}, ON",
                        addr,
                        flags=re.IGNORECASE,
                    )
        return addr


class ScraperEngine:
    """Handles all network requests and HTML parsing for YellowPages and DuckDuckGo."""

    @staticmethod
    def search_yp(name: str, address: str) -> Dict | None:
        """Searches YellowPages.ca for a specific business to find Phone/Website."""
        match = re.search(r"([^,]+),\s*(ON|Ontario)", address, flags=re.IGNORECASE)
        loc = match.group(1).strip() if match else "ON"

        url = f"https://www.yellowpages.ca/search/si/1/{name.replace(' ', '+')}/{loc.replace(' ', '+')}"

        try:
            time.sleep(random.uniform(0.1, 0.5))
            res = requests.get(url, headers=get_headers(), timeout=8)
            if res.status_code != 200:
                return None

            soup = BeautifulSoup(res.text, "html.parser")
            listing = soup.find("div", class_="listing__content__wrapper")
            if not listing:
                return None

            phone_tag = listing.find("h4", class_="impl_phone_number") or listing.find(
                "li", class_="mlr__item--phone"
            )
            phone = phone_tag.get_text(strip=True) if phone_tag is not None else "N/A"

            website = "N/A"
            website_item = listing.find("li", class_="mlr__item--website")
            if website_item:
                link_tag = website_item.find("a")
                href = link_tag.get("href") if link_tag is not None else None
                if href:
                    website = f"https://www.yellowpages.ca{href}"
                    if "redirect=" in website:
                        parsed = urlparse(website)
                        query_params = parse_qs(parsed.query)
                        redirect_list = query_params.get("redirect")
                        if redirect_list:
                            website = redirect_list[0]

            return {
                "phone": DataCleaner.clean_phone(phone),
                "website": website,
            }
        except Exception:
            return None

    @staticmethod
    def search_ddg(name: str, address: str) -> Dict:
        """Fallback search using DuckDuckGo HTML version if YP fails."""
        match = re.search(r"([^,]+),\s*(ON|Ontario)", address, flags=re.IGNORECASE)
        city = match.group(1).strip() if match else ""
        try:
            time.sleep(random.uniform(0.1, 0.5))
            res = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": f"{name} {city} phone"},
                headers=get_headers(),
                timeout=8,
            )
            soup = BeautifulSoup(res.text, "html.parser")
            text = soup.get_text()

            phones = re.findall(
                r"(?:\+?1[-. ]?)?\(?([2-9][0-9]{2})\)?[-. ]?([2-9][0-9]{2})[-. ]?([0-9]{4})",
                text,
            )
            phone = (
                f"({phones[0][0]}) {phones[0][1]}-{phones[0][2]}" if phones else "N/A"
            )

            website = "N/A"
            for link in soup.find_all("a", class_="result__a"):
                href = link.get("href")
                if (
                    href
                    and "duckduckgo" not in href
                    and not any(x in href for x in ["yelp", "yellowpages", "411.ca"])
                ):
                    website = href
                    break

            return {"phone": phone, "website": website}
        except Exception:
            return {"phone": "N/A", "website": "N/A"}

    @staticmethod
    def generate_yp(keyword: str, location: str) -> List[Dict]:
        """Generates a list of leads (Name, Address) from YellowPages search results."""
        url = f"https://www.yellowpages.ca/search/si/1/{keyword.replace(' ', '+')}/{location.replace(' ', '+')}"
        results: List[Dict] = []
        try:
            time.sleep(random.uniform(0.2, 0.8))
            resp = requests.get(url, headers=get_headers(), timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for listing in soup.find_all("div", class_="listing__content__wrapper"):
                name_tag = listing.find("a", class_="listing__name--link")
                addr_tag = listing.find("span", class_="listing__address--full")
                if name_tag is not None and addr_tag is not None:
                    name = name_tag.get_text(strip=True)
                    address = addr_tag.get_text(strip=True)
                    results.append({"Name": name, "Address": address})
            return results
        except Exception:
            return []


def mass_generate_leads(categories: List[str], locations: List[str]) -> List[Dict]:
    """
    Uses ScraperEngine.generate_yp for each category/location combo.
    Returns de-duplicated leads: {Name, Address, Phone, Website, Source}
    """
    seen = set()
    leads: List[Dict] = []

    for cat in categories:
        for loc in locations:
            res = ScraperEngine.generate_yp(cat, loc)
            for r in res:
                clean_addr = DataCleaner.fix_address(r["Address"])
                key = f"{r['Name'].lower()}|{clean_addr[:32].lower()}"
                if key in seen:
                    continue
                seen.add(key)
                leads.append(
                    {
                        "Name": r["Name"],
                        "Address": clean_addr,
                        "Phone": "N/A",
                        "Website": "N/A",
                        "Source": "YP",
                    }
                )
            time.sleep(random.uniform(0.2, 0.6))

    return leads


def enrich_leads(leads: List[Dict], max_workers: int = 20) -> List[Dict]:
    """
    Enriches leads with phone + website using YP first, then DDG fallback.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _process(row: Dict) -> Dict:
        phone = row.get("Phone", "")
        if phone and phone != "N/A" and len(phone) > 5:
            return {
                **row,
                "Address": DataCleaner.fix_address(row.get("Address", "")),
                "Phone": DataCleaner.clean_phone(phone),
                "Source": row.get("Source", "Keep"),
            }

        name = row["Name"]
        addr = DataCleaner.fix_address(row["Address"])

        d = ScraperEngine.search_yp(name, addr)
        src = "YP"

        if not d or d["phone"] == "N/A":
            d = ScraperEngine.search_ddg(name, addr)
            src = "DDG"

        return {
            **row,
            "Address": addr,
            "Phone": d["phone"],
            "Website": d["website"],
            "Source": src,
        }

    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_process, r) for r in leads]
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception:
                pass
    return results
