"""
Created on 13/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from ptinstancemanager.config import configuration, args
from ptinstancemanager.app import app, db
from ptinstancemanager.models import *
from ptinstancemanager.views import *


def main():
	if args.create_db: # argument set
		db.create_all() # By default it doesn't create already created tables
		init_database(db, app.config['LOWEST_PORT'], app.config['HIGHEST_PORT'])
		# We don't run the app in this mode.
		# Otherwise on its automatic restarts it will try to create the database and data again!
	else:
		app.run(host='0.0.0.0')


if __name__ == "__main__":
    main()
