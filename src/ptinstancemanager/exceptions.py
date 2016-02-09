"""
Created on 09/02/2015
@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""


class InsufficientResourcesError(Exception):
    def __init__(self, message):
        super(InsufficientResourcesError, self).__init__(message)


class DockerContainerError(Exception):
    def __init__(self, message):
        super(InsufficientResourcesError, self).__init__(message)
