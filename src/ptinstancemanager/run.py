"""
Created on 13/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>

Builtin server for development.

Configuration file path is read from program args.
"""

from argparse import ArgumentParser
from ptinstancemanager.config import configuration


def main(config_file):
	configuration.set_file_path(config_file)
	from ptinstancemanager.main import load_app, load_db
	app = load_app()

	if args.create_db:
		db = load_db()
		db.create_all() # By default it doesn't create already created tables
		init_database(db, app.config['LOWEST_PORT'], app.config['HIGHEST_PORT'])
	else:
		# We don't run the app in the database creation mode.
		# Otherwise on flask's automatic restarts it will try to create the database and data again!
		app.run(host='0.0.0.0', debug=True)


if __name__ == "__main__":
	parser = ArgumentParser(description='Run sample web server which uses ptinstancemanager.')
	parser.add_argument('-createdb', action='store_true', dest='create_db',
	                    help='Do you want to create the database? (needed at least the first time)')
	parser.add_argument('-config', default='../../config.ini', dest='config',
	                    help='Configuration file.')
	args = parser.parse_args()

	# Builtin server for development.
	main(args.config)