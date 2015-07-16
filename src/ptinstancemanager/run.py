"""
Created on 13/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from ptinstancemanager.config import configuration, args
from ptinstancemanager.app import app, db
from ptinstancemanager.models import *
from ptinstancemanager.views import *


def load_app():  # E.g., to run in gunicorn using wsgi.py
	# this only exists to invoke the imports above
	return app


def main():
	if args.create_db:
		db.create_all() # By default it doesn't create already created tables
		init_database(db, app.config['LOWEST_PORT'], app.config['HIGHEST_PORT'])
	else:
		# We don't run the app in the database creation mode.
		# Otherwise on flask's automatic restarts it will try to create the database and data again!
		app.run(host='0.0.0.0')


if __name__ == "__main__":
	main()