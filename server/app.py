import os

from dotenv import load_dotenv
from fastapi import Body, FastAPI
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()
client = OpenAI(api_key=os.getenv("OPEN_API_KEY"))

# Model setup
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4.1-mini")
CURRENT_MODEL = DEFAULT_MODEL

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

# 1) Define the request body
class ChatIn(BaseModel):
    user_text: str
    
# 2) Create the /chat endpoint
@app.post("/chat")
def chat(payload: ChatIn):
    response = client.responses.create(
        model= CURRENT_MODEL,
        input= payload.user_text,
        max_output_tokens=200,
        temperature=0.5
    )
    
    return {
        "answer": response.output_text,
        #"model": CURRENT_MODEL,
        "tokens_used": response.usage.total_tokens if response.usage else None
    }


@app.post("/admin/set_model")
def set_model(new_model: str = Body(..., embed=True)):
    """
    Hidden admin-only endpoint to change the model at runtime.
    Users will never see this in the UI.
    """
    
    global CURRENT_MODEL
    CURRENT_MODEL = new_model
    return {"ok": True, "current_model": CURRENT_MODEL}