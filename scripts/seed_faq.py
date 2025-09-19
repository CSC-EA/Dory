from __future__ import annotations

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlmodel import Session, select

from server.db import engine, init_db
from server.models import Faq

load_dotenv()


def now_utc():
    return datetime.now(timezone.utc)


def normalize(q: str) -> str:
    return " ".join(q.lower().strip().split())


# seed expected Qs
SEED_FAQs = [
    {
        "q": "when is the digital engineering summit?",
        "a": "The 2nd Australian Digital Engineering Summit will take place on Monday 24 November 2025 at the National Convention Centre Canberra. Optional workshops and masterclasses will be held on Tuesday 25 November 2025 at the UNSW Canberra City Campus and online.",
    },
    {
        "q": "where is the summit venue?",
        "a": "The main Summit on 24 November 2025 will be held at the National Convention Centre Canberra. The optional workshops and masterclasses on 25 November 2025 will be at the UNSW Canberra City Campus and online.",
    },
    {
        "q": "how much does it cost to attend?",
        "a": "In-person registration is $220 AUD, which includes full summit access, workshops, catering, and networking opportunities. Virtual registration is $110 AUD, which includes full online summit access and the option to attend workshops virtually.",
    },
    {
        "q": "what is included in registration?",
        "a": "In-person registration includes presentations, workshops, morning/afternoon tea, lunch, networking, and a name badge. Virtual registration includes access to all presentations online, workshops, and the ability to ask questions live during sessions.",
    },
    {
        "q": "what is the refund policy?",
        "a": "Registrations are non-refundable. Substitutes are permitted up until 10 November 2025. Changes within 7 days of the Summit incur a $40 AUD administrative fee.",
    },
    {
        "q": "where can i book accommodation?",
        "a": "Delegates can book at the special conference rates through Consec at A by Adina Canberra (Studio Room $275/night) or Crowne Plaza Canberra (City View Room $289/night). Accommodation must be booked via the registration system or by contacting Consec at adesummit@consec.com.au.",
    },
    {
        "q": "who are some of the speakers?",
        "a": "Confirmed speakers include Professor Emma Sparks (UNSW Canberra), Professor Sondoss Elsawah (UNSW Canberra), Mr Terry Saunder (CASG), Ms Lucy Poole (Digital Transformation Agency), Dr Nigel McGinty (DSTG), BRIG Jennifer Harris (Headquarters Indo-Pacific Endeavour 2025), Mr Jawahar Bhalla (Shoal Group & University of Adelaide), Commodore Andrew Macalister (Royal Australian Navy), Dr Barclay Brown (Collins Aerospace), Dr Stephen Craig (CSIRO), Mr Thomas A. McDermott (SERC), Mr Philip Swadling (Thales Australia), Mr Shuzo Otani (ANSYS), and Mr Adrian Piani (GHD).",
    },
    {
        "q": "what sessions are in the program?",
        "a": "The Summit program on 24 November 2025 includes: Session 1 - Engineering Digital Transformation; Session 2 - Driving Innovations Across the Digital Engineering Ecosystem; Session 3 - Driving the Adoption of Digital Engineering: Recruitment, Skillsets & Career Pathways; and Session 4 - Digital Engineering: Creating & Realizing New Value. Morning tea, lunch, and afternoon tea are included.",
    },
    {
        "q": "who manages the summit?",
        "a": "The Summit is managed by Consec – Conference and Event Management. Contact: adesummit@consec.com.au or +61 2 6252 1200.",
    },
]


def main():
    init_db()
    added = 0
    with Session(engine) as db:
        for item in SEED_FAQs:
            qn = normalize(item["q"])
            exists = db.exec(select(Faq).where(Faq.question_norm == qn)).first()
            if exists:
                continue
            db.add(Faq(question_norm=qn, answer=item["a"], created_at=now_utc()))
            added += 1
        db.commit()
    print(f"[seed_faq] Added {added} FAQs.")


if __name__ == "__main__":
    main()
