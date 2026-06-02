# agents/flight_expert.py
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

flight_expert_agent = Agent(
    role="Flight Pricing Expert",
    goal="Estimate realistic flight costs between an origin and a destination.",
    backstory="An expert travel agent specialized in airline routing, historical pricing, and economical travel.",
    llm=mistral_llm,
    verbose=True
)

def create_flight_estimation_task(origin: str, destination: str, currency: str) -> Task:
    """
    Creates a CrewAI Task for estimating flight costs.
    Runs asynchronously alongside Local Expert logic.
    """
    prompt = (
        f"The traveler is departing from {origin} to {destination}. "
        f"Return ONLY valid JSON with a top-level \"est_flight_cost\" object containing the keys low, high, currency representing a realistic "
        f"ECONOMY ROUND-TRIP price PER PERSON from {origin} to {destination}, expressed in {currency}. "
        "Use a tight low–high range that reflects route distance and demand.\n"
        f"Example: {{\"est_flight_cost\": {{\"low\": 540, \"high\": 780, \"currency\": \"{currency}\"}} }}"
    )
    
    return Task(
        description=prompt,
        expected_output="JSON with flight cost estimate containing low, high, and currency.",
        agent=flight_expert_agent
    )