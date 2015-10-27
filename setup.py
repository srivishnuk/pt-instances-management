"""
Created on July 13, 2015

@author: Aitor Gómez Goiri <aitor.gomez-goiri@open.ac.uk>

To install/reinstall/uninstall the project and its dependencies using pip:
     pip install ./
     pip install ./ --upgrade
     pip uninstall ptinstancemanager
"""
from setuptools import setup  # , find_packages

setup(name="ptinstancemanager",
      version="0.1",
      description="Sample web application which manages PT instances.",
      # long_description = "",
      author="Aitor Gomez-Goiri",
      author_email="aitor.gomez-goiri@open.ac.uk",
      maintainer="Aitor Gomez-Goiri",
      maintainer_email="aitor.gomez-goiri@open.ac.uk",
      url="https://github.com/gomezgoiri/pt-instances-management",
      # license = "http://www.apache.org/licenses/LICENSE-2.0",
      platforms=["any"],
      package_dir={
          '': 'src',
      },
      packages=["ptinstancemanager"],
      install_requires=["docker-py", "Flask-SQLAlchemy", "flasgger"],
      entry_points={
          'console_scripts': [
              'run-api = ptinstancemanager.run:entry_point',
          ],
      },
)
