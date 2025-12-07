from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import (
    CATEGORIES,
    NORTHERN_LOCATIONS,
    mass_generate_leads,
    enrich_leads,
)

app = FastAPI(title="NorthScrape API")


# CORS so your dashboard on kathail.ca can call this API
origins = [
    "https://kathail.ca",
    "https://www.kathail.ca",
    "https://kathail.ca/northscrape",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    categories: List[str]
    locations: List[str]
    enrich: bool = True


@app.get("/api/meta")
def meta():
    return {
        "categories": CATEGORIES,
        "locations": NORTHERN_LOCATIONS,
        "version": "1.0",
    }


@app.post("/api/generate")
def generate(req: GenerateRequest):
    if not req.categories or not req.locations:
        return {"error": "categories and locations cannot be empty"}

    leads = mass_generate_leads(req.categories, req.locations)

    if req.enrich:
        leads = enrich_leads(leads)

    return {"count": len(leads), "leads": leads}
