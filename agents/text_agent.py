from flask import Flask, request
import requests, json
from google import genai

client = genai.Client(api_key="AIzaSyBZ7LA5XV7kdbJLvLtNswCMirlxdo4l6w0")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="what is the meaning of life",
)

## save output in json
output = {"text_output": response.text}
with open("text_agent_output.json", "a") as f:
    json.dump(output, f, indent=2)
