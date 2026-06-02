# agents/local_expert.py
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
local_expert_agent = Agent(
    role="Local Expert",
    goal="Suggest specific places, restaurants, and activities in a destination",
    backstory="A seasoned local guide who knows the best spots and hidden gems of their city.",
    llm=mistral_llm,
    verbose=True
)

def create_local_expert_task(inputs: dict) -> Task:
    """
    Creates a CrewAI Task for getting local places of interest.
    Configured to run asynchronously to enable parallel execution.
    """
    destination = inputs.get("destination", "the destination")
    interests = inputs.get("interests", [])
    special_requirements = inputs.get("special_requirements", "")
    
    num_days = int(inputs.get("num_days") or 1)
    target_count = max(6, min(20, num_days * 3))

    prompt = (
        f"Based on the user's interests: {interests} and special requirements: '{special_requirements}', "
        f"suggest about {target_count} places to visit, eat, or do in {destination} across a {num_days}-day trip "
        f"(plan for ~3 stops per day so the itinerary stays well-paced).\n\n"

        "⚠️  STRICT ACCURACY RULES — VERY IMPORTANT:\n\n"

        "RULE 1 — REAL PLACES ONLY:\n"
        f"Every place you suggest MUST be a real, well-known, currently operating establishment or "
        f"landmark in {destination} that can be found on Google Maps.\n"
        "Do NOT invent or fabricate place names. Do NOT combine a real place with an activity "
        "that is NOT actually offered there.\n"
        "Examples of what NOT to do:\n"
        "- 'Jet Skiing at Hussain Sagar Lake' — jet skiing is NOT available at Hussain Sagar.\n"
        "- 'Parasailing at Tank Bund' — parasailing is NOT offered at Tank Bund.\n"
        "If an activity (e.g. water sports, adventure sports) is not genuinely offered at a location, "
        "do NOT suggest it. Instead, suggest an activity that IS actually available there "
        "(e.g. 'Boating at Hussain Sagar Lake' — boating IS available).\n\n"

        "RULE 2 — STRICT LOCATION:\n"
        f"Every place MUST physically exist WITHIN the city limits of {destination} "
        f"or within a 30 km radius of {destination}'s city center.\n"
        f"Do NOT suggest places from other cities, even if they are famous. "
        f"For example, if the destination is Hyderabad, do NOT include beaches from Goa, Mumbai, or Kerala. "
        f"If the destination is Jaipur, do NOT include the Taj Mahal (it is in Agra).\n\n"

        "RULE 3 — IMPOSSIBLE INTERESTS:\n"
        f"If the user's interests include activities that are geographically impossible in {destination} "
        f"(e.g., beaches in a landlocked city, skiing in a desert, scuba diving without ocean), "
        f"do NOT suggest them. Instead, suggest the closest LOCAL alternative that genuinely exists "
        f"and mention why in the tips field.\n"
        f"For example, in Hyderabad: instead of beaches → suggest boating at Hussain Sagar or visiting "
        f"Shamirpet Lake; instead of skiing → suggest Snow World (indoor snow park) if it exists, "
        f"otherwise skip.\n\n"

        "Return valid JSON with two top-level fields:\n"
        f"- \"currency\" (string, the ISO 4217 code of the local currency used in {destination}, e.g. 'EUR', 'JPY', 'INR', 'USD')\n"
        "- \"places\" (array)\n\n"
        "Each element of \"places\" must include:\n"
        "- id (string, unique identifier like 'p1')\n"
        "- name (string — use the OFFICIAL name as it appears on Google Maps)\n"
        "- type (string: exactly one of 'attraction', 'restaurant', 'activity', 'transit', 'lodging')\n"
        "- hours_needed (float, estimated time to spend there)\n"
        "- prereqs (array of strings, e.g., ['book in advance', 'wear walking shoes'])\n"
        "- tips (string, local advice)\n"
        f"- cost (float, estimated cost per person in the LOCAL currency of {destination} — NOT in USD)\n"
        "- currency (string, same ISO 4217 code as the top-level currency, included on every place for clarity)\n"
        "- lat (float, latitude)\n"
        "- lng (float, longitude)\n\n"
        f"IMPORTANT: All cost values must be in the local currency of {destination}. "
        "Do NOT convert to USD.\n"
        "CRITICAL: Do not use double quotes inside your string values. Use single quotes instead to avoid breaking JSON parsing.\n"
    )

    return Task(
        description=prompt,
        expected_output="JSON containing the local currency and a list of recommended places.",
        agent=local_expert_agent
    )
