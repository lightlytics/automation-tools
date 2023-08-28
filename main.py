import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, Any
from src.python.common.logger import Logger
from starlette.background import BackgroundTasks
from starlette.requests import Request
app = FastAPI()
log = Logger().get_logger()

from src.python.utilities import generate_cost_report as cost_report
from src.python.utilities import generate_cost_recommendations as cost_recommendations
from src.python.utilities import generate_compliance_report as compliance_report
from src.python.utilities import export_inventory as export_inventory


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/generate_cost_report")
def generate_cost_report(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Generate Cost Report requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name'], payload['start_timestamp'], payload['end_timestamp'], payload['period'],
                 payload.get('stage', None)]
    try:
        file_name = cost_report.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_cost_recommendations")
def generate_cost_recommendations(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Generate Cost Recommendations requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name'], payload.get('stage', None)]
    try:
        file_name = cost_recommendations.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_compliance_report")
async def generate_compliance_report(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Generate Compliance Report requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name'], payload['compliance_standard'],
                 payload.get('accounts', None), payload.get('label', None), payload.get('stage', None)]
    try:
        file_name = compliance_report.main(*arguments)
        headers = {'Content-Disposition': f'attachment; filename="{file_name}"'}
        background_tasks.add_task(remove_file, file_name)
        return FileResponse(file_name, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_export_inventory")
def generate_export_inventory(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export inventory requested - {payload['environment_sub_domain']}")
    arguments = [payload['environment_sub_domain'], payload['environment_user_name'], payload['environment_password'],
                 payload['ws_name'], payload['resource_type'],
                 payload.get('accounts', None), payload.get('tags', None), payload.get('stage', None)]
    try:
        file_name = export_inventory.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def remove_file(path: str) -> None:
    log.info(f'Removing file "{path}"')
    os.unlink(path)


if __name__ == "__main__":
    uvicorn.run(app, port=80, host="0.0.0.0")
