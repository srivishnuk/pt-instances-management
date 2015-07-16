"""
Created on 16/07/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from ptinstancemanager.config import configuration

def main(config_file):
	configuration.set_file_path(config_file)
	from ptinstancemanager.run import main
	main()