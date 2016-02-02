"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import logging
from flask import Flask
from celery import Celery
from flask.ext.sqlalchemy import SQLAlchemy
from flasgger import Swagger
from ptinstancemanager.config import configuration


def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery



# Configure logging
FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(filename=configuration.get_log(), level=logging.DEBUG, format=FORMAT)

# Create web application
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = configuration.get_database_uri()
app.config['LOWEST_PORT'] = configuration.get_lowest_port()
app.config['HIGHEST_PORT'] = configuration.get_highest_port()
app.config['MAXIMUM_CPU'] = configuration.get_maximum_cpu()
app.config['MAXIMUM_MEMORY'] = configuration.get_maximum_memory()
app.config['DOCKER_URL'] =  configuration.get_docker_url()
app.config['DOCKER_IMAGE'] = configuration.get_docker_image_name()
app.config['DOCKER_DATA_ONLY'] = configuration.get_docker_data_container()
app.config['DOCKER_VNC_PORT'] =  configuration.get_docker_vnc_port()
app.config['DOCKER_PT_PORT'] =  configuration.get_docker_pt_port()
app.config['CACHE_DIR'] =  configuration.get_cache_directory()
app.config['CACHE_CONTAINER_DIR'] =  configuration.get_container_directory()
app.config['CELERY_BROKER_URL'] = configuration.get_celery_broker_url()
app.config['CELERY_RESULT_BACKEND'] = configuration.get_celery_broker_url()
app.config['CELERY_TIMEOUT'] = configuration.get_celery_timeout()
app.config['CELERY_IMPORTS'] = ('ptinstancemanager.tasks',)
app.config['PT_CHECKER'] = configuration.get_jar_path()
app.config['SWAGGER'] = {
    "swagger_version": "2.0",
    "title": "pt-instances-management",
    "specs": [{
            "version": "0.0.1",
            "title": "API v1",
            "endpoint": 'v1_spec',
            "route": '/spec',
            "rule_filter": lambda rule: rule.endpoint.startswith('v1'),
    }],
}
swagger = Swagger(app)

# Configure DB
db = SQLAlchemy(app)

# Configure celery
celery = make_celery(app)
