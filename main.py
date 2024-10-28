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
from src.python.utilities import generate_cost_report_main_pipeline as cost_report_main_pipeline
from src.python.utilities import export_flow_logs as export_fl
from src.python.utilities import export_ec2_os_info as export_ec2_os
from src.python.utilities import export_eks_cost_data as export_k8s_cost
from src.python.utilities import generate_vulnerabilities_report as export_vuln
from src.python.utilities import export_inventory_count_by_account


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/generate_cost_report")
def generate_cost_report(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Generate Cost Report requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload['start_timestamp'], payload['end_timestamp'], payload['period'],
                 payload.get('ignore_discounts', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
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


@app.post("/generate_cost_report_main_pipeline")
def generate_cost_report(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Generate Cost Report Main Pipeline requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload['start_timestamp'], payload['end_timestamp'], payload['period']]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = cost_report_main_pipeline.main(*arguments)
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
    log.info(f"### Generate Cost Recommendations requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name']]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
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


@app.post("/export_ec2_os_info")
def generate_cost_recommendations(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export EC2 Instances OS Info requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name']]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = export_ec2_os.main(*arguments)
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
    log.info(f"### Generate Compliance Report requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload['compliance_standard'], payload.get('accounts', None), payload.get('label', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = compliance_report.main(*arguments)
        headers = {'Content-Disposition': f'attachment; filename="{file_name}"'}
        background_tasks.add_task(remove_file, file_name)
        return FileResponse(file_name, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_export_inventory")
def generate_export_inventory(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export inventory requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload['resource_type'], payload.get('accounts', None), payload.get('tags', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
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


@app.post("/export_inventory_count")
def export_inventory_count(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export inventory count requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload.get('accounts', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = export_inventory_count_by_account.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/export_flow_logs")
def export_flow_logs(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export Flow Logs requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload.get('action', None), payload.get('dst_resource_id', None), payload.get('start_time', None),
                 payload.get('end_time', None), payload.get('src_public', None), payload.get('protocols', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = export_fl.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/export_eks_cost")
def export_eks_cost(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export EKS Cost requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload['start_timestamp'], payload['end_timestamp']]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = export_k8s_cost.main(*arguments)
        headers = {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{file_name}"'
        }
        background_tasks.add_task(remove_file, file_name)
        with open(file_name) as csv_file:
            return StreamingResponse(iter([csv_file.read()]), headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/export_vulnerabilities")
def export_vulnerabilities(payload: Dict[Any, Any], background_tasks: BackgroundTasks):
    log.info(f"### Export Vulnerabilities requested - {payload['environment_sub_domain'].replace('!', '')}")
    arguments = [payload['environment_sub_domain'].replace('!', ''), payload['environment_user_name'],
                 payload['environment_password'], payload.get('environment_f2a_token', None), payload['ws_name'],
                 payload.get('publicly_exposed', None), payload.get('exploit_available', None),
                 payload.get('fix_available', None), payload.get('cve_id', None), payload.get('severity', None)]
    if payload['environment_sub_domain'].startswith('!'):
        arguments.append("true")
    try:
        file_name = export_vuln.main(*arguments)
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
