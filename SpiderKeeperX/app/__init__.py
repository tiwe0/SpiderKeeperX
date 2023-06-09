import os
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from SpiderKeeperX.app.spider.controller import api_router
from SpiderKeeperX.config import DB_PATH
from SpiderKeeperX.app.spider.model import Base, engine
from SpiderKeeperX.app.proxy.spiderctrl import SpiderAgent
from SpiderKeeperX.app.proxy.contrib.scrapy import ScrapydProxy
import SpiderKeeperX.config as config

agent = SpiderAgent()

def regist_server():
    if config.SERVER_TYPE == 'scrapyd':
        for server in config.SERVERS:
            agent.regist(ScrapydProxy(server))

scheduler = BackgroundScheduler()


def start_scheduler():
    from SpiderKeeperX.app.schedulers.common import sync_job_execution_status_job, sync_spiders, \
        reload_runnable_spider_job_execution
    scheduler.add_job(sync_job_execution_status_job, 'interval', seconds=5, id='sys_sync_status')
    scheduler.add_job(sync_spiders, 'interval', seconds=10, id='sys_sync_spiders')
    scheduler.add_job(reload_runnable_spider_job_execution, 'interval', seconds=30, id='sys_reload_job')
    scheduler.start()

def init_db():
    print("init db.")
    if not os.path.exists(DB_PATH):
        print("create db file.")
        with open(DB_PATH, mode="wb"):
            pass
    Base.metadata.create_all(engine, Base.metadata.tables.values(), checkfirst=True)

def init_all():
    init_db()
    pass

def build_app():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="./SpiderKeeperX/app/static"), name="static")
    app.include_router(api_router)
    start_scheduler()
    regist_server()
    return app