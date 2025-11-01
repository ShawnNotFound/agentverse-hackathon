import os
import sys
import json
from google import genai

# Text agent entrypoint and function. Reads GENAI_API_KEY from environment.
API_KEY = os.environ.get("GENAI_API_KEY") or "AIzaSyBZ7LA5XV7kdbJLvLtNswCMirlxdo4l6w0"

def generate_text(prompt: str) -> str:
    """Generate text using GenAI and persist to `text_agent_output.json`.

    Returns the generated text.
    """
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    output = {"text_output": response.text}
    # write (overwrite) the output file so UI can read latest
    with open("text_agent_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    return response.text


if __name__ == "__main__":
    # Allow calling as: python agents/text_agent.py "your prompt here"
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "what is the meaning of life"
    try:
        text = generate_text(prompt)
        print(text)
    except Exception as exc:
        print(f"Error generating text: {exc}")
        raise
