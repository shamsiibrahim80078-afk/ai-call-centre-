"""
Phase 3 autonomous simulation — 20 fake businesses through full scout pipeline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.scout_agent import ScoutAgent
from brain.lead_prioritizer import priority_summary
from database import initialize_database, list_leads


FAKE_BUSINESSES = [
    {
        "business_name": "Sunrise Dental Care",
        "website": "https://sunrise-dental-care.example",
        "phone": "+1-512-555-0101",
        "email": "front@sunrise-dental-care.example",
        "industry": "healthcare",
        "city": "Austin",
        "country": "USA",
        "about": "Family dentistry. Call us. No online booking.",
        "html_length": 2200,
        "text_length": 480,
        "social_links": [],
    },
    {
        "business_name": "Metro Legal Partners",
        "website": "https://metro-legal-partners.example",
        "phone": "+1-212-555-0144",
        "email": None,
        "industry": "legal",
        "city": "New York",
        "country": "USA",
        "about": "Law firm specializing in contracts.",
        "html_length": 3100,
        "text_length": 900,
        "social_links": ["https://linkedin.com/company/metro-legal"],
    },
    {
        "business_name": "GreenLeaf Landscaping",
        "website": "https://greenleaf-landscaping.example",
        "phone": "+1-303-555-0190",
        "email": "jobs@greenleaf-landscaping.example",
        "industry": "construction",
        "city": "Denver",
        "country": "USA",
        "about": "Landscaping and outdoor design. Contact form coming soon.",
        "html_length": 1800,
        "text_length": 300,
        "social_links": [],
    },
    {
        "business_name": "Nova Fitness Studio",
        "website": "https://nova-fitness-studio.example",
        "phone": "+1-415-555-0112",
        "email": "hello@nova-fitness-studio.example",
        "industry": "fitness",
        "city": "San Francisco",
        "country": "USA",
        "about": "Gym memberships and personal training.",
        "html_length": 4500,
        "text_length": 1500,
        "social_links": ["https://instagram.com/novafit"],
    },
    {
        "business_name": "Harbor Seafood Grill",
        "website": "https://harbor-seafood-grill.example",
        "phone": "+1-206-555-0177",
        "email": "reserve@harbor-seafood-grill.example",
        "industry": "restaurant",
        "city": "Seattle",
        "country": "USA",
        "about": "Waterfront restaurant. Menu online. No chatbot.",
        "html_length": 5200,
        "text_length": 2100,
        "social_links": ["https://facebook.com/harborseafood", "https://instagram.com/harborseafood"],
    },
    {
        "business_name": "PixelCraft Marketing",
        "website": "https://pixelcraft-marketing.example",
        "phone": "+1-312-555-0133",
        "email": "growth@pixelcraft-marketing.example",
        "industry": "marketing",
        "city": "Chicago",
        "country": "USA",
        "about": "SEO and advertising agency. Book a strategy call.",
        "html_length": 12000,
        "text_length": 4000,
        "social_links": [
            "https://linkedin.com/company/pixelcraft",
            "https://twitter.com/pixelcraft",
            "https://instagram.com/pixelcraft",
        ],
    },
    {
        "business_name": "Summit Realty Group",
        "website": "https://summit-realty-group.example",
        "phone": "+1-702-555-0188",
        "email": "agents@summit-realty-group.example",
        "industry": "real_estate",
        "city": "Las Vegas",
        "country": "USA",
        "about": "Homes for sale. Schedule a showing.",
        "html_length": 9000,
        "text_length": 3200,
        "social_links": ["https://facebook.com/summitrealty"],
    },
    {
        "business_name": "BrightMind Tutoring",
        "website": "https://brightmind-tutoring.example",
        "phone": "+1-617-555-0155",
        "email": None,
        "industry": "education",
        "city": "Boston",
        "country": "USA",
        "about": "Private tutoring academy for STEM.",
        "html_length": 1600,
        "text_length": 280,
        "social_links": [],
    },
    {
        "business_name": "CloudNest SaaS",
        "website": "https://cloudnest-saas.example",
        "phone": "+1-646-555-0121",
        "email": "sales@cloudnest-saas.example",
        "industry": "saas",
        "city": "New York",
        "country": "USA",
        "about": "Workflow software platform with API integrations and AI automation.",
        "html_length": 28000,
        "text_length": 9000,
        "social_links": [
            "https://linkedin.com/company/cloudnest",
            "https://twitter.com/cloudnest",
            "https://youtube.com/@cloudnest",
            "https://facebook.com/cloudnest",
        ],
    },
    {
        "business_name": "Oak & Iron Carpentry",
        "website": "https://oak-iron-carpentry.example",
        "phone": "+1-503-555-0166",
        "email": "shop@oak-iron-carpentry.example",
        "industry": "construction",
        "city": "Portland",
        "country": "USA",
        "about": "Custom carpentry contractor.",
        "html_length": 1400,
        "text_length": 220,
        "social_links": [],
    },
    {
        "business_name": "Velvet Spa Retreat",
        "website": "https://velvet-spa-retreat.example",
        "phone": "+1-310-555-0198",
        "email": "book@velvet-spa-retreat.example",
        "industry": "healthcare",
        "city": "Los Angeles",
        "country": "USA",
        "about": "Spa treatments. Appointment booking available via Calendly.",
        "html_length": 7000,
        "text_length": 2500,
        "social_links": ["https://instagram.com/velvetspa", "https://facebook.com/velvetspa"],
    },
    {
        "business_name": "Northwind Auto Repair",
        "website": "https://northwind-auto-repair.example",
        "phone": "+1-612-555-0142",
        "email": "service@northwind-auto-repair.example",
        "industry": "automotive",
        "city": "Minneapolis",
        "country": "USA",
        "about": "Auto repair shop. Get in touch for estimates.",
        "html_length": 2500,
        "text_length": 600,
        "social_links": [],
    },
    {
        "business_name": "BlueRiver Accounting",
        "website": "https://blueriver-accounting.example",
        "phone": "+1-704-555-0171",
        "email": "office@blueriver-accounting.example",
        "industry": "finance",
        "city": "Charlotte",
        "country": "USA",
        "about": "Bookkeeping and tax prep. Contact us.",
        "html_length": 3300,
        "text_length": 1100,
        "social_links": ["https://linkedin.com/company/blueriver"],
    },
    {
        "business_name": "Sparkle Clean Co",
        "website": "https://sparkle-clean-co.example",
        "phone": "+1-407-555-0119",
        "email": None,
        "industry": "services",
        "city": "Orlando",
        "country": "USA",
        "about": "Residential cleaning services.",
        "html_length": 1100,
        "text_length": 180,
        "social_links": [],
    },
    {
        "business_name": "Alpine Outdoor Gear",
        "website": "https://alpine-outdoor-gear.example",
        "phone": "+1-801-555-0182",
        "email": "shop@alpine-outdoor-gear.example",
        "industry": "ecommerce",
        "city": "Salt Lake City",
        "country": "USA",
        "about": "Online store for hiking gear. Cart and checkout enabled.",
        "html_length": 15000,
        "text_length": 5000,
        "social_links": ["https://instagram.com/alpinegear", "https://facebook.com/alpinegear"],
    },
    {
        "business_name": "Civic Tech Labs",
        "website": "https://civic-tech-labs.example",
        "phone": "+1-202-555-0150",
        "email": "hello@civic-tech-labs.example",
        "industry": "saas",
        "city": "Washington",
        "country": "USA",
        "about": "Government software. Live chat and AI automation roadmap.",
        "html_length": 22000,
        "text_length": 7000,
        "social_links": ["https://linkedin.com/company/civictech", "https://twitter.com/civictech"],
    },
    {
        "business_name": "Golden Crust Bakery",
        "website": "https://golden-crust-bakery.example",
        "phone": "+1-215-555-0138",
        "email": "orders@golden-crust-bakery.example",
        "industry": "restaurant",
        "city": "Philadelphia",
        "country": "USA",
        "about": "Artisan bakery. Place orders by phone.",
        "html_length": 2000,
        "text_length": 400,
        "social_links": ["https://instagram.com/goldencrust"],
    },
    {
        "business_name": "IronPeak Security",
        "website": "https://ironpeak-security.example",
        "phone": "+1-214-555-0160",
        "email": "ops@ironpeak-security.example",
        "industry": "services",
        "city": "Dallas",
        "country": "USA",
        "about": "Private security contractor. Contact form available.",
        "html_length": 4800,
        "text_length": 1600,
        "social_links": [],
    },
    {
        "business_name": "Lumen Photo Studio",
        "website": "https://lumen-photo-studio.example",
        "phone": "+1-305-555-0127",
        "email": "book@lumen-photo-studio.example",
        "industry": "services",
        "city": "Miami",
        "country": "USA",
        "about": "Portrait photography. Book now online.",
        "html_length": 6000,
        "text_length": 2200,
        "social_links": ["https://instagram.com/lumenphoto", "https://facebook.com/lumenphoto"],
    },
    {
        "business_name": "Cascade Pet Clinic",
        "website": "https://cascade-pet-clinic.example",
        "phone": "+1-503-555-0193",
        "email": "care@cascade-pet-clinic.example",
        "industry": "healthcare",
        "city": "Eugene",
        "country": "USA",
        "about": "Veterinary clinic. Appointment scheduling and contact us page.",
        "html_length": 8000,
        "text_length": 2800,
        "social_links": ["https://facebook.com/cascadepets"],
    },
]


def main() -> None:
    print("=" * 60)
    print("PHASE 3 AUTONOMOUS SIMULATION — 20 BUSINESSES")
    print("=" * 60)
    initialize_database()
    scout = ScoutAgent(name="Scout-Simulation")
    results = scout.scout_batch(FAKE_BUSINESSES)
    created = sum(1 for r in results if r["created"])
    duplicates = sum(1 for r in results if r["duplicate"])
    print(f"[OK] processed={len(results)} created={created} duplicates={duplicates}")

    # Re-run first 3 to prove duplicate prevention at scale
    rerun = scout.scout_batch(FAKE_BUSINESSES[:3])
    assert all(r["duplicate"] for r in rerun)
    print("[OK] re-run duplicate prevention verified")

    leads = list_leads(limit=1000)
    sim_sites = {b["website"].rstrip("/") for b in FAKE_BUSINESSES}
    sim_leads = [l for l in leads if (l.get("website") or "").rstrip("/") in sim_sites]
    assert len(sim_leads) >= 20
    print(f"[OK] sqlite simulation leads={len(sim_leads)}")

    dashboard = priority_summary(sim_leads)
    report = {
        "total_leads": dashboard["total_leads"],
        "high_priority": dashboard["high_priority"],
        "medium_priority": dashboard["medium_priority"],
        "low_priority": dashboard["low_priority"],
        "average_opportunity_score": dashboard["average_opportunity_score"],
        "average_automation_score": dashboard["average_automation_score"],
        "average_priority_score": dashboard["average_priority_score"],
    }
    print("\n=== DASHBOARD REPORT ===")
    print(json.dumps(report, indent=2))
    out = _ROOT / "logs" / "phase3_dashboard_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"report": report, "leads": dashboard["leads"]}, indent=2), encoding="utf-8")
    print(f"[OK] dashboard written to {out}")
    print("=" * 60)
    print("PHASE 3 SIMULATION: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
