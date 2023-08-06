import os
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from typing import Dict, Any

from src.python.utilities import generate_cost_report as cost_report
from src.python.utilities import generate_cost_recommendations as cost_recommendations

app = FastAPI()


@app.middleware("http")
async def after_request(request: Request, call_next):
    response: Response = await call_next(request)
    directory = os.getcwd()
    files = os.listdir(directory)
    for f in files:
        if f.endswith(".csv"):
            os.remove(os.path.join(directory, f))
    return response


@app.get("/generate_cost_report")
def generate_cost_report(payload: Dict[Any, Any]):
    file_name = cost_report.main(
        payload['environment_sub_domain'],
        payload['environment_user_name'],
        payload['environment_password'],
        payload['ws_name'],
        payload['start_timestamp'],
        payload['end_timestamp'],
        payload['period']
    )
    headers = {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{file_name}"'
    }
    with open(file_name) as csv_file:
        return StreamingResponse(iter([csv_file.read()]), headers=headers)


@app.get("/generate_cost_recommendations")
def generate_cost_recommendations(payload: Dict[Any, Any]):
    file_name = cost_recommendations.main(
        payload['environment_sub_domain'],
        payload['environment_user_name'],
        payload['environment_password'],
        payload['ws_name']
    )
    headers = {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename="{file_name}"'
    }
    with open(file_name) as csv_file:
        return StreamingResponse(iter([csv_file.read()]), headers=headers)


if __name__ == "__main__":
    uvicorn.run(app, port=80, host="0.0.0.0")
