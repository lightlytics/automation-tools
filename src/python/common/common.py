import logging
import os
import sys

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.graph_common import GraphCommon
    from src.python.common.logger import Logger
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.graph_common import GraphCommon
    from src.python.common.logger import Logger

log = logging.getLogger("stream_external_tools")
if len(log.handlers) == 0:
    log = Logger().get_logger()


def get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage):
    log.info(f"Trying to login into Stream in environment {environment}")
    ll_url = f"https://{environment}.streamsec.io"
    if stage:
        ll_url = f"https://{environment}.lightops.io"
    ll_graph_url = f"{ll_url}/graphql"
    try:
        graph_client = GraphCommon(ll_graph_url, ll_username, ll_password, otp=ll_f2a)
        ws_id = graph_client.get_ws_id_by_name(ws_name)
        graph_client.change_client_ws(ws_id)
        log.info("Logged in successfully!")
        return graph_client
    except Exception as e:
        log.error(f"Couldn't login to the system, error: {e}")
        raise Exception(e)
