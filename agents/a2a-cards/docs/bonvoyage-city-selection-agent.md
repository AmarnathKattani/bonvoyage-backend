# BonVoyage City Selection Agent

An AI-powered **Destination Analyst** that recommends travel cities based on user interests, personality traits, and budget constraints. Built on the [A2A (Agent-to-Agent) protocol](https://google.github.io/A2A/) v0.2.9, this agent integrates into multi-agent travel planning workflows.

---

## Overview

The City Selection Agent analyzes traveler preferences and returns a scored list of destination recommendations. Each suggestion includes weather forecasts, estimated flight costs, and geographic coordinates — enabling downstream agents (Local Expert, Flight Expert, Travel Concierge) to continue the planning pipeline without additional lookups.

### Key Capabilities

- Matches user interests and personality traits to ideal destinations
- Budget-aware filtering with per-day cost-of-tourism analysis
- Flight cost estimation (economy round-trip per person) from the traveler's origin
- Weather summaries for each recommended city
- GPS coordinates for map rendering and distance calculations

---

## Agent Card

| Field               | Value                                              |
|---------------------|----------------------------------------------------|
| **Name**            | BonVoyage City Selection Agent                     |
| **Version**         | 1.0.0                                              |
| **Protocol**        | A2A v0.2.9                                         |
| **Provider**        | BonVoyage Travel AI                                |
| **Input Modes**     | `application/json`, `text/plain`                   |
| **Output Modes**    | `application/json`                                 |
| **Streaming**       | No                                                 |
| **Push Notifications** | No                                              |

---

## Skills

### City Recommendation

Recommends travel destinations by matching user preferences (interests, personality traits, budget) to ideal cities. Returns a scored list of city suggestions including weather, estimated flight costs, and GPS coordinates.

**Skill ID:** `city-recommendation`

**Tags:** `travel` · `destination` · `city-selection` · `budget` · `recommendation`

---

## Request Format

### Input Schema (`application/json`)

```json
{
  "interests": ["beach", "nightlife", "museums"],
  "destination_traits": ["vibrant", "walkable", "historic"],
  "budget": {
    "amount": 2000,
    "currency": "USD"
  },
  "origin": "New York",
  "num_days": 5,
  "num_suggestions": 3
}
```

### Input Fields

| Field                | Type       | Required | Description                                                  |
|----------------------|------------|----------|--------------------------------------------------------------|
| `interests`          | `string[]` | Yes      | Activities the traveler enjoys (e.g., `beach`, `hiking`)     |
| `destination_traits` | `string[]` | No       | Desired city characteristics (e.g., `walkable`, `historic`)  |
| `budget.amount`      | `number`   | Yes      | Total on-ground budget for the trip                          |
| `budget.currency`    | `string`   | Yes      | ISO 4217 currency code (e.g., `USD`, `EUR`, `INR`)          |
| `origin`             | `string`   | No       | Departure city for flight cost estimation                    |
| `num_days`           | `integer`  | No       | Trip duration in days (used for per-day budget calculation)  |
| `num_suggestions`    | `integer`  | No       | Number of destination suggestions to return (default: `1`)   |

> **Note:** The budget covers on-ground spend (attractions, food, local transit). Flights and lodging are tracked separately by downstream agents.

---

## Response Format

### Output Schema (`application/json`)

```json
{
  "suggestions": [
    {
      "city": "Lisbon",
      "country": "Portugal",
      "score": 0.94,
      "rationale": "Affordable European capital — daily activity spend fits comfortably in the budget.",
      "weather_summary": "Mid-70s °F, dry, 11 hrs sun",
      "est_flight_cost": {
        "low": 540,
        "high": 780,
        "currency": "USD"
      },
      "center": {
        "lat": 38.7223,
        "lng": -9.1393
      }
    }
  ]
}
```

### Output Fields

| Field                          | Type     | Description                                                |
|--------------------------------|----------|------------------------------------------------------------|
| `suggestions`                  | `array`  | Ranked list of destination recommendations                 |
| `suggestions[].city`           | `string` | Recommended city name                                      |
| `suggestions[].country`        | `string` | Country the city belongs to                                |
| `suggestions[].score`          | `float`  | Relevance score (0.0–1.0), higher = better fit             |
| `suggestions[].rationale`      | `string` | Explanation of why this city matches the traveler's profile |
| `suggestions[].weather_summary`| `string` | Current/seasonal weather overview                          |
| `suggestions[].est_flight_cost`| `object` | Economy round-trip flight estimate per person               |
| `suggestions[].est_flight_cost.low`  | `number` | Lower bound of the fare range                        |
| `suggestions[].est_flight_cost.high` | `number` | Upper bound of the fare range                        |
| `suggestions[].est_flight_cost.currency` | `string` | Currency code (matches `budget.currency`)        |
| `suggestions[].center`         | `object` | Geographic coordinates of the city center                  |
| `suggestions[].center.lat`     | `float`  | Latitude                                                   |
| `suggestions[].center.lng`     | `float`  | Longitude                                                  |

---

## Usage Examples

### Example 1 — Beach Vacation on a Budget

**Request:**

```json
{
  "interests": ["beach", "seafood", "water sports"],
  "destination_traits": ["tropical", "affordable"],
  "budget": { "amount": 1500, "currency": "USD" },
  "origin": "Chicago",
  "num_days": 5,
  "num_suggestions": 3
}
```

**Response:**

```json
{
  "suggestions": [
    {
      "city": "Cancún",
      "country": "Mexico",
      "score": 0.96,
      "rationale": "Top beach destination with affordable dining — daily on-ground costs well within $300/day.",
      "weather_summary": "85°F, sunny, occasional afternoon showers",
      "est_flight_cost": { "low": 280, "high": 420, "currency": "USD" },
      "center": { "lat": 21.1619, "lng": -86.8515 }
    }
  ]
}
```

### Example 2 — Family Museum Trip in Europe

**Request:**

```json
{
  "interests": ["museums", "history", "kid-friendly activities"],
  "destination_traits": ["walkable", "safe", "historic"],
  "budget": { "amount": 3000, "currency": "EUR" },
  "origin": "London",
  "num_days": 7,
  "num_suggestions": 2
}
```

---

## Architecture

```
┌─────────────────────┐
│   Client / Frontend  │
└─────────┬───────────┘
          │  POST /plan
          ▼
┌─────────────────────┐
│   Trip Orchestrator   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  City Selection      │────▶│  Local Expert     │────▶│  Travel Concierge  │
│  Agent (this agent)  │     │  Agent            │     │  Agent             │
└─────────────────────┘     └──────┬───────────┘     └────────────────────┘
                                   │
                            ┌──────┴───────────┐
                            │  Flight Expert    │
                            │  Agent            │
                            └──────────────────┘
```

The City Selection Agent is the **first agent** in the BonVoyage planning pipeline. Its output feeds directly into the Local Expert and Flight Expert agents for enrichment.

---

## Technical Details

| Property         | Value                          |
|------------------|--------------------------------|
| **Framework**    | CrewAI                         |
| **LLM Provider** | Mistral AI                     |
| **Model**        | `mistral-small-latest`         |
| **Temperature**  | 0.3                            |
| **Role**         | Destination Analyst            |

---

## Error Handling

| Scenario                    | Behavior                                                     |
|-----------------------------|--------------------------------------------------------------|
| Missing `interests`         | Returns generic popular destinations                         |
| Invalid `budget.currency`   | Falls back to `USD`                                          |
| No `origin` provided        | Flight estimates use generic economy round-trip pricing      |
| LLM rate limit (429)        | Automatic retry with exponential backoff (up to 3 attempts)  |
| Malformed LLM response      | JSON repair via `json_repair` library, falls back to `{}`    |

---

## Related Agents

| Agent                    | Role                                                          |
|--------------------------|---------------------------------------------------------------|
| **Local Expert Agent**   | Discovers attractions, restaurants, and activities at the chosen destination |
| **Flight Expert Agent**  | Provides detailed flight cost estimates between origin and destination       |
| **Travel Concierge Agent** | Builds a day-by-day itinerary from the selected places                    |
