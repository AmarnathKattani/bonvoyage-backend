# agents/travel_concierge.py
from crewai import Agent, Task, LLM
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize CrewAI native LLM client
mistral_llm = LLM(
    model="mistral/mistral-small-latest",
    api_key=os.getenv("MISTRAL_API_KEY"),
    temperature=0.3
)

# Instantiate the standard CrewAI agent
travel_concierge_agent = Agent(
    role="Travel Concierge",
    goal="Construct a well-paced daily itinerary from a list of places",
    backstory="An expert travel planner who excels at logistics, pacing, and crafting memorable daily schedules.",
    llm=mistral_llm,
    verbose=True
)

def create_travel_concierge_task(inputs: dict) -> Task:
    """
    Creates a CrewAI Task for planning a detailed itinerary.
    """
    destination = inputs.get("destination", "the destination")
    num_days = inputs.get("num_days", 2)
    places = inputs.get("places", [])
    refinement = (inputs.get("refinement") or "").strip()
    current_itinerary = inputs.get("current_itinerary")

    places_summary = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "hours_needed": p.get("hours_needed"),
            "lat": p.get("lat"),
            "lng": p.get("lng"),
        }
        for p in places
    ]

    base_prompt = (
        f"Create a realistic {num_days}-day itinerary for {destination} using ONLY the following places:\n"
        f"{places_summary}\n\n"
        f"CRITICAL DISTRIBUTION RULES — your output is graded on these:\n"
        f"1. The \"days\" array MUST contain EXACTLY {num_days} day objects, numbered 1 through {num_days}.\n"
        f"2. Spread the places EVENLY across all {num_days} days — DO NOT pile every place into Day 1.\n"
        f"3. Every day MUST have at least 2 blocks and at most 3 blocks. Do NOT put more than 3 places "
        f"in a single day — the traveler needs a relaxed pace. If you have leftover places, spread them "
        f"to other days or leave them out.\n"
        f"4. GEOGRAPHIC PROXIMITY IS THE #1 GROUPING RULE: Look at the lat/lng coordinates above. "
        f"Places that are geographically close to each other (within 5 km) MUST be on the SAME day. "
        f"Never put two places on opposite sides of the city on the same day if closer alternatives exist. "
        f"Order the blocks within each day so the traveler moves in a logical route, not zigzagging.\n"
        f"5. NEVER use the same place_id more than once across the entire itinerary. "
        f"Every block must reference a UNIQUE place_id. No repeats.\n"
        f"6. Alternate restaurant/meal blocks between sightseeing blocks — don't stack multiple "
        f"attractions back-to-back without a meal break.\n"
        "\nReturn ONLY valid JSON with a top-level \"itinerary\" object containing a \"days\" array. "
        "Do not include any extra text, notes, or markdown outside the JSON.\n"
        "CRITICAL: Do not use double quotes inside your string values. Use single quotes instead to avoid breaking JSON parsing.\n"
        "Each element in the \"days\" array must represent a day and include:\n"
        "- day (integer, 1-indexed)\n"
        "- theme (string, a catchy title for the day)\n"
        "- blocks (array of objects, each containing: place_id (string, MUST match the provided ids), start (string, e.g., '09:00 AM'), end (string, e.g., '11:30 AM'), notes (string, why to visit then))\n\n"
    )

    if refinement:
        existing_blocks = []
        if isinstance(current_itinerary, dict):
            for d in current_itinerary.get("days", []) or []:
                existing_blocks.append({
                    "day": d.get("day"),
                    "theme": d.get("theme"),
                    "blocks": [
                        {
                            "place_id": b.get("place_id"),
                            "start": b.get("start"),
                            "end": b.get("end"),
                        }
                        for b in (d.get("blocks") or [])
                    ],
                })
        refinement_block = (
            "\n\nREFINEMENT REQUEST FROM THE TRAVELER (highest priority — honor it):\n"
            f"\"{refinement}\"\n\n"
            "The traveler already has the following itinerary. Modify it according to the request "
            "above. Keep the parts they didn't ask to change. Do not invent new places — stick to "
            "the place_id values from the list provided earlier. Reorder, retime, swap, or drop "
            "blocks as needed to satisfy the request, while still respecting hours_needed and a "
            "humane pace.\n\n"
            f"EXISTING ITINERARY:\n{existing_blocks}\n"
        )
        prompt = base_prompt + refinement_block
    else:
        prompt = base_prompt

    return Task(
        description=prompt,
        expected_output="JSON containing the structured daily itinerary.",
        agent=travel_concierge_agent
    )
