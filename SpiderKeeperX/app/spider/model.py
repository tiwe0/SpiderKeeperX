import datetime
from sqlalchemy import desc, select
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, INTEGER, Text, DATETIME, Integer, DateTime, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import sqlalchemy

from SpiderKeeperX.config import SQLALCHEMY_DATABASE_URI

engine = create_engine(SQLALCHEMY_DATABASE_URI)
session = Session(engine)

class Base(DeclarativeBase):
    __abstract__ = True

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    date_created = Column(DateTime, default=sqlalchemy.func.current_timestamp())
    date_modified = Column(DateTime, default=sqlalchemy.func.current_timestamp(),
                              onupdate=sqlalchemy.func.current_timestamp())

class Project(Base):
    __tablename__ = 'skx_project'

    project_name = Column(String(50))

    @classmethod
    def load_project(cls, project_list):
        for project in project_list:
            existed_project = session.execute(select(cls).filter_by(project_name=project.project_name)).scalar_one()
            if not existed_project:
                session.add(project)
                session.commit()

    @classmethod
    def find_project_by_id(cls, project_id):
        return session.execute(select(Project).where(Project.id==project_id)).scalar_one()

    def to_dict(self):
        return {
            "project_id": self.id,
            "project_name": self.project_name
        }

class SpiderInstance(Base):
    __tablename__ = 'skx_spider'

    spider_name = Column(String(100))
    project_id = Column(INTEGER, nullable=False, index=True)

    @classmethod
    def update_spider_instances(cls, project_id, spider_instance_list):
        for spider_instance in spider_instance_list:
            existed_spider_instance = session.execute(select(cls).filter_by(project_id=project_id,
                                                          spider_name=spider_instance.spider_name)).scalar_one()
            if not existed_spider_instance:
                session.add(spider_instance)
                session.commit()

        for spider in session.execute(select(cls).filter_by(project_id=project_id)).scalars():
            existed_spider = any(
                spider.spider_name == s.spider_name
                for s in spider_instance_list
            )
            if not existed_spider:
                session.delete(spider)
                session.commit()

    @classmethod
    def list_spider_by_project_id(cls, project_id):
        return session.execute(select(cls).filter_by(project_id=project_id)).scalars()

    def to_dict(self):
        return dict(spider_instance_id=self.id,
                    spider_name=self.spider_name,
                    project_id=self.project_id)

    @classmethod
    def list_spiders(cls, project_id):
        sql_last_runtime = text('''
            select * from (select a.spider_name,b.date_created from skx_job_instance as a
                left join skx_job_execution as b
                on a.id = b.job_instance_id
                order by b.date_created desc) as c
                group by c.spider_name
            ''')
        sql_avg_runtime = text('''
            select a.spider_name,avg(end_time-start_time) from skx_job_instance as a
                left join skx_job_execution as b
                on a.id = b.job_instance_id
                where b.end_time is not null
                group by a.spider_name
            ''')
        last_runtime_list = dict(
            (spider_name, last_run_time) for spider_name, last_run_time in session.execute(sql_last_runtime))
        avg_runtime_list = dict(
            (spider_name, avg_run_time) for spider_name, avg_run_time in session.execute(sql_avg_runtime))
        res = []
        for spider in session.execute(select(cls).filter_by(project_id=project_id)).scalars():
            last_runtime = last_runtime_list.get(spider.spider_name)
            res.append(dict(spider.to_dict(),
                            **{'spider_last_runtime': last_runtime if last_runtime else '-',
                               'spider_avg_runtime': avg_runtime_list.get(spider.spider_name)
                               }))
        return res


class JobPriority():
    LOW, NORMAL, HIGH, HIGHEST = range(-1, 3)


class JobRunType():
    ONETIME = 'onetime'
    PERIODIC = 'periodic'


class JobInstance(Base):
    __tablename__ = 'skx_job_instance'

    spider_name = Column(String(100), nullable=False, index=True)
    project_id = Column(INTEGER, nullable=False, index=True)
    tags = Column(Text)  # job tag(split by , )
    spider_arguments = Column(Text)  # job execute arguments(split by , ex.: arg1=foo,arg2=bar)
    priority = Column(INTEGER)
    desc = Column(Text)
    cron_minutes = Column(String(20), default="0")
    cron_hour = Column(String(20), default="*")
    cron_day_of_month = Column(String(20), default="*")
    cron_day_of_week = Column(String(20), default="*")
    cron_month = Column(String(20), default="*")
    enabled = Column(INTEGER, default=0)  # 0/-1
    run_type = Column(String(20))  # periodic/onetime

    def to_dict(self):
        return dict(
            job_instance_id=self.id,
            spider_name=self.spider_name,
            tags=self.tags.split(',') if self.tags else None,
            spider_arguments=self.spider_arguments,
            priority=self.priority,
            desc=self.desc,
            cron_minutes=self.cron_minutes,
            cron_hour=self.cron_hour,
            cron_day_of_month=self.cron_day_of_month,
            cron_day_of_week=self.cron_day_of_week,
            cron_month=self.cron_month,
            enabled=self.enabled == 0,
            run_type=self.run_type

        )

    @classmethod
    def list_job_instance_by_project_id(cls, project_id):
        return session.execute(select(cls).filter_by(project_id=project_id)).scalars()

    @classmethod
    def find_job_instance_by_id(cls, job_instance_id):
        return session.execute(select(cls).filter_by(id=job_instance_id)).scalar_one()

class SpiderStatus():
    PENDING, RUNNING, FINISHED, CANCELED = range(4)

class JobExecution(Base):
    __tablename__ = 'skx_job_execution'

    project_id = Column(INTEGER, nullable=False, index=True)
    service_job_execution_id = Column(String(50), nullable=False, index=True)
    job_instance_id = Column(INTEGER, nullable=False, index=True)
    create_time = Column(DATETIME)
    start_time = Column(DATETIME)
    end_time = Column(DATETIME)
    running_status = Column(INTEGER, default=SpiderStatus.PENDING)
    running_on = Column(Text)

    def to_dict(self):
        job_instance = session.execute(select(JobInstance).filter_by(id=self.job_instance_id)).scalar_one()
        return {
            'project_id': self.project_id,
            'job_execution_id': self.id,
            'job_instance_id': self.job_instance_id,
            'service_job_execution_id': self.service_job_execution_id,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'start_time': self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else None,
            'end_time': self.end_time.strftime('%Y-%m-%d %H:%M:%S') if self.end_time else None,
            'running_status': self.running_status,
            'running_on': self.running_on,
            'job_instance': job_instance.to_dict() if job_instance else {}
        }

    @classmethod
    def find_job_by_service_id(cls, service_job_execution_id):
        return session.execute(select(cls).filter_by(service_job_execution_id=service_job_execution_id)).scalar_one()

    @classmethod
    def list_job_by_service_ids(cls, service_job_execution_ids):
        return session.execute(select(cls).filter(cls.service_job_execution_id.in_(service_job_execution_ids))).scalars()

    @classmethod
    def list_uncomplete_job(cls):
        return session.execute(select(cls).filter(cls.running_status != SpiderStatus.FINISHED,
                                cls.running_status != SpiderStatus.CANCELED)).scalars()

    @classmethod
    def list_jobs(cls, project_id, each_status_limit=100):
        result = {}
        result['PENDING'] = [job_execution.to_dict() for job_execution in
                            session.execute(select(JobExecution).filter_by( project_id=project_id, running_status=SpiderStatus.PENDING
                            ).order_by(desc(JobExecution.date_modified)).limit(each_status_limit))]
        result['RUNNING'] = [job_execution.to_dict() for job_execution in
                            session.execute(select(JobExecution).filter_by(project_id=project_id, running_status=SpiderStatus.RUNNING).order_by(
                                 desc(JobExecution.date_modified)).limit(each_status_limit))]
        result['COMPLETED'] = [job_execution.to_dict() for job_execution in
        session.execute(select(JobExecution).filter(JobExecution.project_id == project_id).filter(
                                   (JobExecution.running_status == SpiderStatus.FINISHED) | (
                                       JobExecution.running_status == SpiderStatus.CANCELED)).order_by(
                                   desc(JobExecution.date_modified)).limit(each_status_limit))]
        return result

    @classmethod
    def list_run_stats_by_hours(cls, project_id):
        result = {}
        hour_keys = []
        last_time = datetime.datetime.now() - datetime.timedelta(hours=23)
        last_time = datetime.datetime(last_time.year, last_time.month, last_time.day, last_time.hour)
        for hour in range(23, -1, -1):
            time_tmp = datetime.datetime.now() - datetime.timedelta(hours=hour)
            hour_key = time_tmp.strftime('%Y-%m-%d %H:00:00')
            hour_keys.append(hour_key)
            result[hour_key] = 0  # init
        for job_execution in session.execute(select(JobExecution).filter(JobExecution.project_id == project_id, JobExecution.date_created >= last_time)).scalars():
            hour_key = job_execution.create_time.strftime('%Y-%m-%d %H:00:00')
            result[hour_key] += 1
        return [dict(key=hour_key, value=result[hour_key]) for hour_key in hour_keys]
