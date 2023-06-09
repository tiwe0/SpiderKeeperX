import os
import tempfile
import subprocess
import datetime

import requests
from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Request, Form, Header, UploadFile
from fastapi.templating import Jinja2Templates

from werkzeug.utils import secure_filename
from git import Repo
from os import path

from SpiderKeeperX.app.spider.model import JobInstance, Project, JobExecution, SpiderInstance, JobRunType, session
from sqlalchemy import select
from SpiderKeeperX.app.proxy.spiderctrl import SpiderAgent

agent = SpiderAgent()

'''
======= Context Processor
'''

def inject_common(request):
    return dict(now=datetime.datetime.now(),
                servers=agent.servers)

def inject_project(request):
    _session = {}
    project_context = {}
    project_context['project_list'] = session.execute(select(Project)).all()
    if project_context['project_list'] and (not _session.get('project_id')):
        project = session.execute(select(Project)).first()
        _session['project_id'] = project.id
    if _session.get('project_id'):
        project_context['project'] = Project.find_project_by_id(_session['project_id'])
        project_context['spider_list'] = [spider_instance.to_dict() for spider_instance in
                        session.query(SpiderInstance).where(SpiderInstance.project_id==_session['project_id']).all()]
    else:
        project_context['project'] = {}
    return project_context

def utility_processor(request):
    def timedelta(end_time, start_time):
        '''
        :param end_time:
        :param start_time:
        :param unit: s m h
        :return:
        '''
        if not end_time or not start_time:
            return ''
        if type(end_time) == str:
            end_time = datetime.datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
        if type(start_time) == str:
            start_time = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        total_seconds = (end_time - start_time).total_seconds()
        return readable_time(total_seconds)

    def readable_time(total_seconds):
        if not total_seconds:
            return '-'
        if total_seconds < 60:
            return '%s s' % total_seconds
        if total_seconds < 3600:
            return '%s m' % int(total_seconds / 60)
        return '%s h %s m' % (int(total_seconds / 3600), int((total_seconds % 3600) / 60))

    return dict(timedelta=timedelta, readable_time=readable_time)

def compat_flask(request):
    return {
        'get_flashed_messages': lambda: None
    }

templates = Jinja2Templates(
    directory="./SpiderKeeperX/app/templates",
    context_processors=[inject_common, inject_project, utility_processor, compat_flask]
    )

'''
========= Router =========
'''

api_router = APIRouter()

@api_router.get("/")
def index():
    project = session.execute(select(Project)).first()
    if project:
        return RedirectResponse(url=f"/project/{project.id}/job/dashboard", code=302)
    return RedirectResponse(url="/project/manage", status_code=302)

@api_router.post("/project/create")
def project_create(project_name: str = Form()):
    project = Project()
    project.project_name = project_name
    session.add(project)
    session.commit()
    return RedirectResponse(url=f"/project/{project.id}/spider/deploy", status_code=302)

@api_router.get("/project/{project_id}/delete")
def project_delete(project_id):
    project = Project.find_project_by_id(project_id)
    agent.delete_project(project)
    session.delete(project)
    session.commit()
    return RedirectResponse(url="/project/manage", status_code=302)

@api_router.get("/project/manage")
def project_manage(request: Request):
    return templates.TemplateResponse("project_manage.html", {"request": request})

@api_router.get("/project/{project_id}")
def project_index(project_id: int):
    return RedirectResponse(url=f"/project/{project_id}/job/dashboard", status_code=302)

@api_router.get("/project/{project_id}/job/dashboard")
def job_dashboard(request: Request, project_id):
    return templates.TemplateResponse("job_dashboard.html", {"request": request, "job_status": JobExecution.list_jobs(project_id)})

@api_router.get("/project/{project_id}/job/periodic")
def job_periodic(request: Request, project_id):
    project = Project.find_project_by_id(project_id)
    job_instance_list = [job_instance.to_dict() for job_instance in
                         session.execute(select(JobInstance).filter_by(run_type="periodic", project_id=project_id)).scalars()]
    return templates.TemplateResponse("job_periodic.html", {"request": request, "job_instance_list": job_instance_list})

@api_router.post("/project/{project_id}/job/add")
def job_add(project_id,
            spider_name: str = Form(),
            spider_arguments: str = Form(),
            priority: int = Form(),
            run_type: str = Form(),
            daemon: str = Form(),
            cron_minutes: str = Form(),
            cron_hour: str = Form(),
            cron_day_of_month: str = Form(),
            cron_day_of_week: str = Form(),
            cron_month: str = Form(),
            cron_exp: str = Form(),
            referrer: str = Header()
            ):
    project = Project.find_project_by_id(project_id)
    job_instance = JobInstance()
    job_instance.spider_name = spider_name
    job_instance.project_id = project_id
    job_instance.spider_arguments = spider_arguments
    job_instance.priority = priority
    job_instance.run_type = run_type
    # chose daemon manually
    if daemon != 'auto':
        spider_args = []
        if spider_arguments:
            spider_args = spider_arguments.split(",")
        spider_args.append("daemon={}".format(daemon))
        job_instance.spider_arguments = ','.join(spider_args)
    if job_instance.run_type == JobRunType.ONETIME:
        job_instance.enabled = -1
        session.add(job_instance)
        session.commit()
        agent.start_spider(job_instance)
    if job_instance.run_type == JobRunType.PERIODIC:
        job_instance.cron_minutes = cron_minutes or '0'
        job_instance.cron_hour = cron_hour or '*'
        job_instance.cron_day_of_month = cron_day_of_month or '*'
        job_instance.cron_day_of_week = cron_day_of_week or '*'
        job_instance.cron_month = cron_month or '*'
        # set cron exp manually
        if cron_exp:
            job_instance.cron_minutes, job_instance.cron_hour, job_instance.cron_day_of_month, job_instance.cron_day_of_week, job_instance.cron_month = \
                cron_exp.split(' ')
        session.add(job_instance)
        session.commit()
    return RedirectResponse(url=referrer, status_code=302)

@api_router.get("/project/{project_id}/jobexecs/{job_exec_id}/stop")
def job_stop(project_id, job_exec_id, referrer: str = Header()):
    job_execution = JobExecution.query.filter_by(project_id=project_id, id=job_exec_id).first()
    agent.cancel_spider(job_execution)
    return RedirectResponse(url=referrer, status_code=302)

@api_router.get("/project/{project_id}/jobexecs/{job_exec_id}/log")
def job_log(request: Request ,project_id, job_exec_id):
    job_execution = JobExecution.query.filter_by(project_id=project_id, id=job_exec_id).first()
    res = requests.get(agent.log_url(job_execution))
    res.encoding = 'utf8'
    raw = res.text
    return templates.TemplateResponse("job_log.html", {"request": request, "log_lines":raw.split('\n')})

@api_router.get("/project/{project_id}/job/{job_instance_id}/run")
def job_run(project_id, job_instance_id, referrer: str = Header()):
    job_instance = JobInstance.query.filter_by(project_id=project_id, id=job_instance_id).first()
    agent.start_spider(job_instance)
    return RedirectResponse(url=referrer, status_code=302)

@api_router.get("/project/{project_id}/job/{job_instance_id}/remove")
def job_remove(project_id, job_instance_id, referrer: str = Header()):
    job_instance = JobInstance.query.filter_by(project_id=project_id, id=job_instance_id).first()
    session.delete(job_instance)
    session.commit()
    return RedirectResponse(url=referrer, status_code=302)

@api_router.get("/project/{project_id}/job/{job_instance_id}/switch")
def job_switch(project_id, job_instance_id, referrer: str = Header()):
    job_instance = JobInstance.query.filter_by(project_id=project_id, id=job_instance_id).first()
    job_instance.enabled = -1 if job_instance.enabled == 0 else 0
    session.commit()
    return RedirectResponse(url=referrer, status_code=302)

@api_router.get("/project/{project_id}/spider/dashboard")
def spider_dashboard(request: Request, project_id):
    spider_instance_list = SpiderInstance.list_spiders(project_id)
    return templates.TemplateResponse("spider_dashboard.html", {"request": request, "spider_instance_list": spider_instance_list})

@api_router.get("/project/{project_id}/spider/deploy")
def spider_deploy(request: Request, project_id):
    project = Project.find_project_by_id(project_id)
    return templates.TemplateResponse("spider_deploy.html", {"request": request})

@api_router.post("/project/{project_id}/spider/upload")
def spider_egg_upload(project_id, file: UploadFile, referrer: str = Header()):
    project = Project.find_project_by_id(project_id)
    # if user does not select file, browser also
    # submit a empty part without filename
    if file.filename == '':
        return RedirectResponse(url=referrer)
    if file:
        filename = secure_filename(file.filename)
        dst = os.path.join(tempfile.gettempdir(), filename)
        file.save(dst)
        agent.deploy(project, dst)
    return RedirectResponse(referrer)

@api_router.post("/project/{project_id}/spider/sync")
async def spider_git_sync(project_id, request: Request, referrer: str = Header()):
    project = Project.find_project_by_id(project_id)
    form = await request.form()
    if form['project-git-uri'].strip() == '':
        return RedirectResponse(url=referrer)
    git_uri = form['project-git-uri'].strip()
    with tempfile.TemporaryDirectory() as tmp_dir:
        Repo.clone_from(git_uri, tmp_dir)
        # TODO
        git_project_name = form['project-git-uri-name']
        git_project_root = path.join(tmp_dir, git_project_name)
        p = subprocess.Popen(["scrapyd-deploy", "--build-egg", f"{git_project_name}.egg", "include-dependencies"], cwd=git_project_root)
        p.wait()
        git_egg_path = path.join(git_project_root, f"{git_project_name}.egg")
        agent.deploy(project, git_egg_path)
    return RedirectResponse(referrer)

@api_router.get("/project/{project_id}/project/stats")
def project_stats(request: Request, project_id):
    project = Project.find_project_by_id(project_id)
    run_stats = JobExecution.list_run_stats_by_hours(project_id)
    return templates.TemplateResponse("project_stats.html", {"request": request, "run_stats": run_stats})

@api_router.get("/project/{project_id}/server/stats")
def service_stats(request: Request, project_id):
    project = Project.find_project_by_id(project_id)
    run_stats = JobExecution.list_run_stats_by_hours(project_id)
    return templates.TemplateResponse("project_stats.html", {"request": request, "run_stats": run_stats})
