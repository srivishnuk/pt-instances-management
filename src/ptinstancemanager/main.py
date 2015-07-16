"""
Created on 16/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

# This module mainly exists to invoke the imports above in the correct order.
from ptinstancemanager.app import app, db
from ptinstancemanager.models import *
from ptinstancemanager.views import *


def load_app(): 
	# Useful to run in gunicorn using wsgi.py
	return app

def load_db():
	return db
