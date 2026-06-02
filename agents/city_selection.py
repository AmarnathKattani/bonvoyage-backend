# agents/city_selection.py
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
city_selection_agent = Agent(
    role="Destination Analyst",
    goal="Recommend destinations based on interests, traits, and budget",
    backstory="You are an expert travel destination analyst who matches user preferences and budgets to the perfect cities.",
    llm=mistral_llm,
    verbose=True
)

def create_city_selection_task(inputs: dict) -> Task:
    """
    Creates a CrewAI Task for selecting cities based on user inputs.
    """
    interests = inputs.get("interests", [])
    traits = inputs.get("destination_traits", [])
    budget = inputs.get("budget", {})
    num_suggestions = inputs.get("num_suggestions", 1)
    origin = (inputs.get("origin") or "").strip()
    budget_currency = (budget.get("currency") or "USD").upper()
    
    # Trip length impacts the daily on-ground budget logic
    num_days = int(inputs.get("num_days") or 1)
    budget_amount = budget.get("amount") or 0
    budget_str = f"{budget_amount} {budget_currency}".strip()

    if origin:
        flight_clause = (
            f"\nFlight cost guidance — the traveler is departing from {origin}. "
            f"Estimate a realistic ECONOMY ROUND-TRIP price PER PERSON from {origin} to each suggested city. "
            f"Use a tight `low`–`high` range that reflects the route distance and demand. "
            f"Express the amounts in {budget_currency} (matching the traveler's budget currency)."
        )
    else:
        flight_clause = (
            f"\nFlight cost guidance — origin not specified, so produce a generic economy round-trip "
            f"per-person estimate in {budget_currency}."
        )

    per_day_budget = (budget_amount / num_days) if (budget_amount and num_days) else 0
    budget_clause = (
        f"\nBudget guidance — the traveler set a TOTAL budget of {budget_str} for a {num_days}-day trip "
        f"(roughly {per_day_budget:.0f} {budget_currency} per day for activities and meals). "
        f"This budget COVERS ON-GROUND SPEND (attractions, food, local transit) — flights and lodging are tracked separately. "
        f"Only recommend cities where a typical traveler can comfortably enjoy the trip within that on-ground budget. "
        f"Reject destinations where typical activity/meal costs would clearly exceed it.\n"
        f"Prefer cities whose typical daily cost-of-tourism is at or below the per-day figure above."
    )

    prompt = (
        f"Recommend {num_suggestions} cities that match these interests: {interests}, "
        f"traits: {traits}, and fit within a budget of {budget_str}.\n"
        f"{budget_clause}\n"
        f"{flight_clause}\n\n"
        "Return ONLY valid JSON with a top-level \"suggestions\" array. Do not include any extra text, notes, or markdown outside the JSON.\n"
        "Each element must include:\n"
        "- city (string)\n"
        "- country (string)\n"
        "- score (float, 0–1, where higher = better budget AND interest fit)\n"
        "- rationale (string, concise — explicitly mention how it fits the budget)\n"
        "- weather_summary (string)\n"
        f"- est_flight_cost (object with low, high, currency — currency MUST be \"{budget_currency}\")\n"
        "- center (object with lat and lng floats)\n\n"
        "Example (origin: New York, budget USD):\n"
        "{\"suggestions\":[{\"city\":\"Lisbon\",\"country\":\"Portugal\",\"score\":0.94,"
        "\"rationale\":\"Affordable European capital — daily activity spend fits comfortably in the budget.\","
        "\"weather_summary\":\"Mid-70s °F, dry, 11 hrs sun\","
        f"\"est_flight_cost\":{{\"low\":540,\"high\":780,\"currency\":\"{budget_currency}\"}},"
        "\"center\":{\"lat\":38.7223,\"lng\":-9.1393}}]}"
    )

    return Task(
        description=prompt,
        expected_output="JSON containing an array of city suggestions matching criteria.",
        agent=city_selection_agent
    )
