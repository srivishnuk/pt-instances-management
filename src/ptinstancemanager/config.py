"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import ConfigParser


class ConfigFileReader(object):

    def __init__(self):
        self.config = ConfigParser.RawConfigParser()

    def set_file_path(self, file_path):
        self.config.read(file_path)

    def get_database_uri(self):
        return self.config.get('Database', 'uri')

    def get_lowest_port(self):
        return self.config.get('Port', 'lowest')

    def get_highest_port(self):
        return self.config.get('Port', 'highest')



configuration = ConfigFileReader()