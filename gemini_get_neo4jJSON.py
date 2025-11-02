# gemini_native_genai.py
# pip install google-generativeai
# Set env: export GEMINI_API_KEY="your_key_here"

from google import genai  
import os
import json

#api_key = 
# Instantiate client (the SDK will read env var x-goog-api-key if configured)
# client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


notes_text = """
Project: Team Nebula — Real-Time Dashboard
Frontend (Dana) finished the dashboard UI and query button.
Backend (Ben) connected FastAPI to data feed.
Bug: Query button sometimes doesn’t re-render charts.
Action: Dana + Ben to pair tomorrow to fix before code freeze.
"""

transcript_text = """
Person1: I'm Alice.
Person2: I'm Dana.
Person3: I'm Ben. 
Alice: Quick sync — Dana, update on the rendering issue?
Dana: The Query button doesn’t always re-render; I think my useEffect hook missed queryParam.
Ben: I’ll help debug it tomorrow morning.
Alice
"""

# prompt = f"""
# Summarize the following `notes_text` and `transcript_text` into a Neo4j-style JSON. 
# First, understand the start of the transcript text to match person+ID to name.

# Include:
# - People (name, role, details, lastActivity)
# - Project (name, description, lastWorkedOn)
# - Issues (title, description, status)
# - Relationships (WORKS_ON, MANAGES, ASSIGNED_TO, AFFECTS), using "from" and "to"
# Return ONLY valid JSON.

# Example detailing schema:
# {{
#   "nodes": [
#     {{
#       "id": "person_alice",
#       "label": "Person",
#       "properties": {{
#         "name": "Alice",
#         "role": "Project Lead",
#         "details": "Ran quick sync; coordinated the fix activity.",
#         "lastActivity": "2025-11-01"
#       }}
#     }}
#   ],
#   "relationships": [
#     {{
#       "id": "r1",
#       "type": "WORKS_ON",
#       "from": "person_dana",
#       "to": "project_team_nebula",
#       "properties": {{}}
#     }}
#   ]
# }}

# notes_text:
# {notes_text}

# transcript_text:
# {transcript_text}
# """

def get_neo4j_json(api_key, notes_text, transcript_text):
    # Use the text-generation / chat-style API. generate_content can accept a text prompt (or multimodal inputs).
    client = genai.Client(api_key=api_key)
    prompt = f"""
    Summarize the following `notes_text` and `transcript_text` into a Neo4j-style JSON. 
    First, understand the start of the transcript text to match person+ID to name.

    Include:
    - People (name, role, details, lastActivity)
    - Project (name, description, lastWorkedOn)
    - Issues (title, description, status)
    - Relationships (WORKS_ON, MANAGES, ASSIGNED_TO, AFFECTS), using "from" and "to"
    Return ONLY valid JSON.

    Example detailing schema:
    {{
    "nodes": [
        {{
        "id": "person_alice",
        "label": "Person",
        "properties": {{
            "name": "Alice",
            "role": "Project Lead",
            "details": "Ran quick sync; coordinated the fix activity.",
            "lastActivity": "2025-11-01"
        }}
        }}
    ],
    "relationships": [
        {{
        "id": "r1",
        "type": "WORKS_ON",
        "from": "person_dana",
        "to": "project_team_nebula",
        "properties": {{}}
        }}
    ]
    }}

    notes_text:
    {notes_text}

    transcript_text:
    {transcript_text}
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"temperature": 0.0}
    )
    text = str(response)
    json_str = text.split("```json")[1].split("```")[0].strip()
    data = json.loads(json_str)
    return json.dumps(data, indent=2)

# # The SDK returns objects with .text() in examples; adjust if your installed SDK returns another shape.
# # Many examples show response.text or response.text() depending on SDK version:
# try:
#     out = response.text
# except Exception:
#     try:
#         out = response.text()
#     except Exception:
#         # fallback to printing the raw response for debugging
#         out = str(response)
api_key = os.getenv("GEMINI_API_KEY")
print(get_neo4j_json(api_key, notes_text, transcript_text))

