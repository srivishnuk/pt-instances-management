"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import argparse
import ConfigParser


class ConfigFileReader(object):

    def __init__(self, file_path):
        self.config = ConfigParser.RawConfigParser()
        self.config.read(file_path)

    def get_lowest_port(self):
        return self.config.get('Port', 'lowest')

    def get_highest_port(self):
        return self.config.get('Port', 'highest')



parser = argparse.ArgumentParser(description='Run sample web server which uses ptinstancemanager.')
parser.add_argument('-createdb', action='store_true', dest='create_db',
                    help='Do you want to create the database? (needed at least the first time)')
parser.add_argument('-config', default='../../config.ini', dest='config',
                    help='Configuration file.')
args = parser.parse_args()
configuration = ConfigFileReader(args.config)