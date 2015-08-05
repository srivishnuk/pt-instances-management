"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flasgger import Swagger
from ptinstancemanager.config import configuration


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = configuration.get_database_uri()
app.config['LOWEST_PORT'] = int(configuration.get_lowest_port())
app.config['HIGHEST_PORT'] = int(configuration.get_highest_port())
app.config['SWAGGER'] = {
    "swagger_version": "2.0",
    "title": "pt-instances-management",
    "specs": [{
            "version": "0.0.1",
            "title": "API v1",
            "endpoint": 'v1_spec',
            "route": '/spec',
            "baseurl": '/',
            "rule_filter": lambda rule: rule.endpoint.startswith('v1'),
    }],
}
swagger = Swagger(app)

db = SQLAlchemy(app)
