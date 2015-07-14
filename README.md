# Packet Tracer instance management

Web application which handles local PacketTracer instances using Docker (see [this project](https://github.com/gomezgoiri/pt-installation) for more info).

Installation
------------

Why would you want to install it?

    pip install git+https://github.com/lightsec/http_bs_lightsec.git


Requirements
------------

The required packages are automatically installed in the procedure described above.

However, if you are going to contribute to this project, you might want to install __only__ the project's dependencies in your [virtualenv](http://virtualenv.readthedocs.org).

You can install them using the _requirements.txt_ file in the following way:

    pip install -r requirements.txt

Usage
-----

1. Run the web server.
   
    ```cd src/ptinstancemanager; python run.py```
