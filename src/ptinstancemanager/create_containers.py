"""
Created on 13/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>

Builtin server for development.

Configuration file path is read from program args.
"""

from argparse import ArgumentParser
from ptinstancemanager.config import configuration


def entry_point():
	parser = ArgumentParser(description='Create containers which will support ptinstancemanager.')
	parser.add_argument('-config', default='../../config.ini', dest='config',
	                    help='Configuration file.')
	parser.add_argument('-number', type=int, default=5, dest='number',
	                    help='Number of containers to create.')
	args = parser.parse_args()

	configuration.set_file_path(args.config)
	from ptinstancemanager.tasks import create_instances
	create_instances(args.number)


if __name__ == "__main__":
	entry_point()
