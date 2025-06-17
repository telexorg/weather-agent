import os, random, httpx
from pprint import pprint
import uvicorn, json
import schemas
from uuid import uuid4
from fastapi import FastAPI, Request, status, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from a2a.utils import new_agent_text_message
from dotenv import load_dotenv

load_dotenv()

WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
WEATHER_API_URL = os.getenv('WEATHER_API_URL')

app = FastAPI()

RAW_AGENT_CARD_DATA = {
  "name": "CurrentWeatherAgent",
  "description": "An agent that accepts a request, creates a task and sends the task status back to the client, keeps processing the task and then sends the task response when the task is completed",
  "url": "",
  "provider": {
      "organization": "Telex Org.",
      "url": "https://telex.im"
    },
  "version": "1.0.0",
  "documentationUrl": "",
  "is_paid": False,
  "price": {},
  "capabilities": {
    "streaming": False,
    "pushNotifications": True
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "weather",
      "name": "Get current Weather",
      "description": "Responds with the current weather.",
      "inputModes": ["text"],
      "outputModes": ["text"],
      "examples": [
        {
          "input": { "parts": [{ "text": "Abuja", "contentType": "text/plain" }] },
          "output": { "parts": [{ "text": "The weather in Abuja is 29.5 degrees but feels like 32.4 degrees. Partly cloudy", "contentType": "text/plain" }] }
        }
      ]
    }
  ]
}


@app.get("/", response_class=HTMLResponse)
def read_root():
    return '<p style="font-size:30px">Current Weather Agent</p>'


@app.get("/.well-known/agent.json")
def agent_card(request: Request):
    current_base_url = str(request.base_url).rstrip("/")

    response_agent_card = RAW_AGENT_CARD_DATA.copy()
    # new_name = f"{response_agent_card['name']}{random.randint(1, 1000)}"
    # print(new_name)
    response_agent_card["url"] = current_base_url
    response_agent_card["provider"]["url"] = current_base_url
    response_agent_card["provider"]["documentationUrl"] = f"{current_base_url}/docs"

    return response_agent_card


async def handle_task(message:str, request_id, task_id: str, webhook_url: str, api_key: str):
  response = None

  async with httpx.AsyncClient() as client:
    response = await client.get(WEATHER_API_URL, params={
                  "key":WEATHER_API_KEY,
                  "q": message
                }
    )

  res = response.json().get("current", {})

  temperature = res.get("temp_c", "not available")
  feels_like = res.get("feelslike_c", None)
  condition : str = res.get("condition", None).get("text", None)

  text = f"The weather in {message.title()} is {temperature} degrees but feels like {feels_like} degrees. {condition.capitalize()}"

  print(text)

  parts = schemas.TextPart(text=text)

  message = schemas.Message(role="agent", parts=[parts])

  artifacts = schemas.Artifact(parts=[parts])

  task = schemas.Task(
    id = task_id,
    status =  schemas.TaskStatus(
      state=schemas.TaskState.COMPLETED, 
      message=schemas.Message(role="agent", parts=[schemas.TextPart(text=text)])
    ),
    artifacts = [artifacts]
  )

  webhook_response = schemas.SendResponse(
      id=request_id,
      result=task
  )

  pprint(webhook_response.model_dump())


  async with httpx.AsyncClient() as client:
    headers = {"X-TELEX-API-KEY": api_key}
    is_sent = await client.post(webhook_url, headers=headers,  json=webhook_response.model_dump(exclude_none=True))
    print(is_sent.status_code)
    pprint(is_sent.json())

  print("background done")
  return 



@app.post("/")
async def handle_request(request: Request, background_tasks: BackgroundTasks):
  try:
    body = await request.json()
    request_id = body.get("id")
    webhook_url = body["params"]["configuration"]["pushNotificationConfig"]["url"]
    api_key = body["params"]["configuration"]["pushNotificationConfig"]["authentication"]["credentials"]


    message = body["params"]["message"]["parts"][0].get("text", None)

    if not message:
      raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Message cannot be empty."
      )
    
    new_task = schemas.Task(
      id = uuid4().hex,
      status =  schemas.TaskStatus(
        state=schemas.TaskState.SUBMITTED, 
        message=schemas.Message(role="agent", parts=[schemas.TextPart(text="In progress")])
      )
    )

    # await handle_task(message, request_id, new_task.id, webhook_url, api_key)
    
    background_tasks.add_task(handle_task, message, request_id, new_task.id, webhook_url, api_key)

    response = schemas.JSONRPCResponse(
       id=request_id,
       result=new_task
    )

  except json.JSONDecodeError as e:
    error = schemas.JSONParseError(
      data = str(e)
    )

    request = await request.json()
    response = schemas.JSONRPCResponse(
       id=request.get("id"),
       error=error
    )

  except Exception as e:
    error = schemas.JSONRPCError(
      code = -32600,
      message = str(e)
    )

    request = await request.json()
    response = schemas.JSONRPCResponse(
       id=request.get("id"),
       error=error
    )

  response = response.model_dump(exclude_none=True)
  pprint(response)
  return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=4000, reload=True)