import os
import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from src.python.common.logger import Logger
app = FastAPI()
log = Logger().get_logger()

from src.python.utilities import generate_cost_report as cost_report
from src.python.utilities import generate_cost_recommendations as cost_recommendations


@app.middleware("http")
async def after_request(request: Request, call_next):
    response: Response = await call_next(request)
    log.info(f"Cleaning up CSV files from the main directory")
    directory = os.getcwd()
    files = os.listdir(directory)
    for f in files:
        if f.endswith(".csv"):
            os.remove(os.path.join(directory, f))
    return response


@app.post("/generate_cost_report")
def generate_cost_report(payload: Dict[Any, Any]):
    log.info(f"Generate Cost Report requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name'], payload['start_timestamp'], payload['end_timestamp'], payload['period']]
    if 'stage' in payload:
        arguments.append(payload['stage'])
    try:
        file_name = cost_report.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_cost_recommendations")
def generate_cost_recommendations(payload: Dict[Any, Any]):
    log.info(f"Generate Cost Recommendations requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name']]
    if 'stage' in payload:
        arguments.append(payload['stage'])
    try:
        file_name = cost_recommendations.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, port=80, host="0.0.0.0")
