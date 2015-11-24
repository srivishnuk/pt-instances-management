"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import ConfigParser
import os


class ConfigFileReader(object):

    def __init__(self):
        self.config = ConfigParser.RawConfigParser()
        self.set_file_path(os.environ.get('PTINSTANCEMNGR'))

    def set_file_path(self, file_path):
        if file_path:  # Ignore if it is None
            self.config.read(file_path)

    def get_log(self):
        return self.config.get('Log', 'file')

    def get_docker_url(self):
        return self.config.get('Docker', 'url')

    def get_docker_image_name(self):
        return self.config.get('Docker', 'image_name')

    def get_docker_data_container(self):
        return self.config.get('Docker', 'data_container')

    def get_docker_vnc_port(self):
        return int(self.config.get('Docker', 'vnc_port'))

    def get_docker_pt_port(self):
        return int(self.config.get('Docker', 'pt_port'))

    def get_database_uri(self):
        return self.config.get('Database', 'uri')

    def get_celery_broker_url(self):
        return self.config.get('Celery', 'broker_url')

    def get_jar_path(self):
        return self.config.get('PTChecker', 'jar_path')

    def get_lowest_port(self):
        return int(self.config.get('Port', 'lowest'))

    def get_highest_port(self):
        return int(self.config.get('Port', 'highest'))

    def get_cache_directory(self):
        ret = self.config.get('CachedFiles', 'cache_dir')
        return ret if ret.endswith('/') else ret + '/'

    def get_container_directory(self):
        ret = self.config.get('CachedFiles', 'container_dir')
        return ret if ret.endswith('/') else ret + '/'


configuration = ConfigFileReader()
