import os
import tempfile
from json import dumps
import configparser
from datetime import datetime
from airflow import configuration
from airflow.settings import DAGS_FOLDER, AIRFLOW_HOME
from airflow.bin.cli import get_dag, CLIFactory
from cwl_airflow.utils.utils import (set_logger,
                                     gen_dag_id,
                                     get_folder,
                                     load_job,
                                     list_files,
                                     export_to_file)
from cwl_airflow.dag_components.cwldag import CWLDAG
from cwl_airflow.dag_components.jobdispatcher import JobDispatcher
from cwl_airflow.dag_components.jobcleanup import JobCleanup


def export_job_file(args):
    job_entry = load_job(args.job)
    del job_entry["id"]
    job_entry['workflow'] = args.workflow
    job_entry['output_folder'] = args.output_folder
    job_entry["uid"] = args.uid
    if args.tmp_folder:
        job_entry['tmp_folder'] = args.tmp_folder
    export_to_file(os.path.join(configuration.get('cwl', 'jobs'), os.path.basename(args.job)),
                   dumps(job_entry, indent=4))


def update_args(args):
    vars(args).update({arg_name: arg_value.default for arg_name, arg_value in CLIFactory.args.items()
                       if arg_name in CLIFactory.subparsers_dict['scheduler']['args']})
    args.dag_id = gen_dag_id(args.workflow, os.path.join(configuration.get('cwl', 'jobs'), os.path.basename(args.job)))
    args.num_runs = len(get_dag(args).tasks) + 3


def get_active_jobs(jobs_folder, limit=10):
    """
    :param jobs_folder: job_folder: abs path to the folder with job json files  
    :param limit: max number of jobs to return
    :return: 
    """
    all_jobs = []
    for job_path in list_files(abs_path=jobs_folder, ext=[".json", ".yml", ".yaml"]):
        job_content = load_job(job_path)
        all_jobs.append({"content": job_content,
                         "path": job_path,
                         "creation_date": datetime.fromtimestamp(os.path.getctime(job_path)),
                         "dag_id": gen_dag_id(job_content["workflow"], job_path)})
    all_jobs = sorted(all_jobs, key=lambda k: k["creation_date"], reverse=True)
    return all_jobs[:limit]


def make_dag(job):
    """
    :param job: {"content": job_entry,
                 "path": job,
                 "creation_date": datetime.fromtimestamp(os.path.getctime(job_path)),
                 "dag_id": gen_dag_id(job_entry["workflow"], job_path)}
    :return:
    """
    set_logger()
    default_args = {
        'start_date': job["creation_date"],
        "job_data":   job,
        'tmp_folder': tempfile.mkdtemp(dir=job["content"].get("tmp_folder", None), prefix="dag_tmp_"),
        'basedir':    os.path.abspath(os.path.dirname(job["path"]))
    }

    dag = CWLDAG(
        dag_id=job["dag_id"],
        schedule_interval='@once',
        default_args=default_args)
    dag.create()
    dag.assign_job_dispatcher(JobDispatcher(dag=dag))
    dag.assign_job_cleanup(JobCleanup(dag=dag))
    return dag


def update_config():
    with open(configuration.AIRFLOW_CONFIG, 'w') as output_stream:
        try:
            configuration.conf.add_section('cwl')
        except configparser.DuplicateSectionError:
            pass
        configuration.set('core', 'dags_are_paused_at_creation', 'False')
        configuration.set('core', 'load_examples', 'False')
        configuration.set('cwl', 'jobs', os.path.join(AIRFLOW_HOME, 'jobs'))
        configuration.set('cwl', 'limit', '10')
        configuration.conf.write(output_stream)


def export_dags():
    dag_content = u"#!/usr/bin/env python3\nfrom airflow import DAG\nfrom cwl_airflow.create_dag import create_dags\nfor id, dag in create_dags().items():\n    globals()[id] = dag"
    export_to_file(os.path.join(DAGS_FOLDER, "cwl_dag.py"), dag_content)


def create_folders():
    get_folder(configuration.get('cwl', 'jobs'))
    get_folder(DAGS_FOLDER)
