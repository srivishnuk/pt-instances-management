"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from ptinstancemanager.config import configuration


app = Flask(__name__)
app.debug = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
app.config['LOWEST_PORT'] = int(configuration.get_lowest_port())
app.config['HIGHEST_PORT'] = int(configuration.get_highest_port())


db = SQLAlchemy(app)