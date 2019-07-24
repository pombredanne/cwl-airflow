import os
import subprocess
import logging
import connexion
from airflow.models import DagBag, TaskInstance, DagRun
from airflow.utils.timezone import parse as parsedate
from airflow.api.common.experimental import trigger_dag


logger = logging.getLogger(__name__)


class CWLAirflowBackend():

    # curl -X GET "127.0.0.1:8080/wes/v1/dags" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dags?dag_ids=example_bash_operator" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dags?dag_ids=example_bash_operator,tutorial" -H "accept: application/json"

    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?dag_id=example_bash_operator&state=running" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?dag_id=example_bash_operator&state=success" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?dag_id=example_bash_operator" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?state=running" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs" -H "accept: application/json"

    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?run_id=scheduled__2019-07-20T00%3A00%3A00%2B00%3A00" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?run_id=scheduled__2019-07-20T00%3A00%3A00%2B00%3A00&dag_id=tutorial" -H "accept: application/json"
    # curl -X GET "127.0.0.1:8080/wes/v1/dag_runs?execution_date=2019-07-20T00%3A00%3A00%2B00%3A00" -H "accept: application/json"

    # curl -X POST "127.0.0.1:8080/wes/v1/dag_runs?dag_id=example_bash_operator&run_id=1234567&conf=%22%7B%7D%22" -H "accept: application/json"

    env = None


    def __init__(self):
        extend_env = {"AIRFLOW__CORE__LOGGING_LEVEL": "ERROR"}
        self.env = os.environ.copy()
        self.env.update(extend_env)


    def get_dags(self, dag_ids=[]):
        logger.debug(f"""Call get_dags with dag_ids={dag_ids}""")
        try:
            dag_ids = dag_ids if dag_ids else self.list_dags()
            logger.debug(f"""Processing dags {dag_ids}""")
            return {"dags": [{"dag_id": dag_id, "tasks": self.list_tasks(dag_id)} for dag_id in dag_ids]}
        except Exception as err:
            logger.error(f"""Failed while running get_dags {err}""")
            return {"dags": []}


    def get_dag_runs(self, dag_id=None, run_id=None, execution_date=None, state=None):
        logger.debug(f"""Call get_dag_runs with dag_id={dag_id}, run_id={run_id}, execution_date={execution_date}, state={state}""")
        try:
            dag_runs = []
            dag_ids = [dag_id] if dag_id else self.list_dags()
            logger.debug(f"""Processing dags {dag_ids}""")
            for d_id in dag_ids:
                logger.debug(f"""Process dag  {d_id}""")
                task_ids = self.list_tasks(d_id)
                logger.debug(f"""Fetched tasks {task_ids}""")
                for dag_run in self.list_dag_runs(d_id, state):
                    logger.debug(f"""Process dag run {dag_run["run_id"]}, {dag_run["execution_date"]}""")
                    if run_id and run_id != dag_run["run_id"] or execution_date and execution_date != dag_run["execution_date"]:
                        logger.debug(f"""Skip dag_run {dag_run["run_id"]}, {dag_run["execution_date"]} (run_id or execution_date doesn't match)""")
                        continue
                    response_item = {"dag_id": d_id,
                                     "run_id": dag_run["run_id"],
                                     "execution_date": dag_run["execution_date"],
                                     "start_date": dag_run["start_date"],
                                     "state": dag_run["state"],
                                     "tasks": []}
                    logger.debug(f"""Get statuses for tasks {task_ids}""")
                    for t_id in task_ids:
                        response_item["tasks"].append({"id": t_id, "state": self.task_state(d_id, t_id, dag_run["execution_date"])})
                    dag_runs.append(response_item)
            return {"dag_runs": dag_runs}
        except Exception as err:
            logger.error(f"""Failed to call get_dag_runs {err}""")
            return {"dag_runs": []}
        

    def post_dag_runs(self, dag_id, run_id=None, conf=None):
        logger.debug(f"""Call post_dag_runs with dag_id={dag_id}, run_id={run_id}, conf={conf}""")
        try:
            dagrun = self.trigger_dag(dag_id, run_id, conf)
            return {"dag_id": dagrun.dag_id,
                    "run_id": dagrun.run_id,
                    "execution_date": dagrun.execution_date,
                    "start_date": dagrun.start_date,
                    "state": dagrun.state}
        except Exception as err:
            logger.error(f"""Failed to call post_dag_runs {err}""")
            return connexion.problem(500, "Failed to create dag_run", str(err))


    def trigger_dag(self, dag_id, run_id, conf):
        return trigger_dag.trigger_dag(dag_id=dag_id, run_id=run_id, conf=conf, replace_microseconds=False)


    def list_dags(self):
        return DagBag().dags.keys()


    def list_tasks(self, dag_id):
        return [t.task_id for t in DagBag().dags[dag_id].tasks]


    def task_state(self, dag_id, task_id, execution_date):
        task_state = TaskInstance(DagBag().dags[dag_id].get_task(task_id=task_id), parsedate(execution_date)).current_state()
        task_state = task_state if task_state else "none"
        return task_state


    def list_dag_runs(self, dag_id, state):
        dag_runs = []
        for dag_run in DagRun.find(dag_id=dag_id, state=state):
            dag_runs.append({
                'run_id': dag_run.run_id,
                'state': dag_run.state,
                'execution_date': dag_run.execution_date.isoformat(),
                'start_date': ((dag_run.start_date or '') and dag_run.start_date.isoformat())
            })
        return dag_runs