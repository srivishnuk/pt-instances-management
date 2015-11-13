"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import os
import errno
import random
import urllib2
import string
from urlparse import urlparse
from flask import redirect, request, render_template, url_for, jsonify
from docker import Client
from werkzeug.exceptions import BadRequest
from ptinstancemanager.app import app
from ptinstancemanager.models import Instance, Port, CachedFile


@app.route("/")
def index():
    return redirect("/apidocs/index.html")

def get_json_error(error_number, message):
    resp = jsonify({ 'status': error_number, 'message': message })
    resp.status_code = error_number
    return resp

@app.errorhandler(404)
def bad_request(error=None):
    return get_json_error(400, 'Bad Request: %s.\n%s' % (request.url, error))

@app.errorhandler(404)
def not_found(error=None):
    return get_json_error(404, 'Not Found: %s.\n%s' % (request.url, error))

@app.errorhandler(500)
def internal_error(error=None):
    return get_json_error(500, 'Internal Server Error: %s' % error)

@app.errorhandler(503)
def unavailable(error=None):
    return get_json_error(503, 'Service Unavailable: %s' % error)

@app.after_request
def add_header(response):
    response.headers['Link'] = ''
    if request.path!='/details':
        response.headers['Link'] += '<%sdetails>; rel="details"; title="Details of API", ' % request.url_root
    if request.path!='/instances':
        response.headers['Link'] += '<%sinstances>; rel="instances"; title="Packet Tracer instances\' management", ' % request.url_root
    if request.path!='/ports':
        response.headers['Link'] += '<%sports>; rel="ports"; title="Ports that can be allocated", ' % request.url_root
    if request.path!='/files':
        response.headers['Link'] += '<%sfiles>; rel="files"; title="Cache for Packet Tracer files", ' % request.url_root
    response.headers['Link'] = response.headers['Link'][:-2]  # Remove last comma and space
    return response

@app.route("/details", endpoint="v1_details")
def get_configuration_details():
    """
    Get API capabilities.
    ---
    tags:
      - details
    responses:
      200:
        description: A single user item
        schema:
          id: Details
          properties:
            lowest_port:
                type: integer
                description: minimum port for newly created instances
            highest_port:
                type: integer
                description: maximum port for newly created instances
    """
    return jsonify( lowest_port=app.config['LOWEST_PORT'],
                    highest_port=app.config['HIGHEST_PORT'] )

def get_host():
    return urlparse(request.base_url).hostname


@app.route("/instances", endpoint="v1_instances")
def list_instances_v1():
    """
    Lists instances.
    ---
    tags:
      - instance
    parameters:
      - name: show
        in: query
        type: string
        description: Show different types of instances
        default: running
        enum: [all, running, finished]
    responses:
      200:
        description: Packet Tracer instances
        schema:
            properties:
                instances:
                    type: array
                    items:
                      $ref: '#/definitions/Instance'
    """
    show_param = request.args.get("show")
    h = get_host()
    if show_param is None or show_param == "running":  # default option
        return jsonify(instances=[ins.serialize("%s/%d" % (request.base_url, ins.id), h) for ins in Instance.get_running()])
    else:
        if show_param not in ("all", "finished"):
            return BadRequest("The 'show' parameter must contain one of the following values: all, running or finished.")

        if show_param == "all":
            return jsonify(instances=[ins.serialize("%s/%d" % (request.base_url, ins.id), h) for ins in Instance.get_all()])  # .limit(10)
        else:  # show_param is "finished":
            return jsonify(instances=[ins.serialize("%s/%d" % (request.base_url, ins.id), h) for ins in Instance.get_finished()])


@app.route("/instances", methods=['POST'], endpoint="v1_instance_create")
def create_instance_v1():
    """
    Creates a new Packet Tracer instance.
    ---
    tags:
      - instance
    responses:
      201:
        description: Packet Tracer instance created
        schema:
          id: Instance
          properties:
            createdAt:
                type: string
                format: date-time
                description: When was the instance created?
            removedAt:
                type: string
                format: date-time
                description: When was the instance removed/stopped?
            id:
                type: integer
                description: Identifier of the instance
            dockerId:
                type: string
                description: Identifier of the docker container which serves the instance
            url:
                type: string
                description: URL to handle the instance
            packetTracer:
                type: string
                description: Host and port where the Packet Tracer instance can be contacted (through IPC)
            vnc:
                type: string
                description: VNC URL to access the Packet Tracer instance
      500:
        description: The container could not be created, there was an error.
        schema:
          id: Error
          properties:
            status:
                type: integer
                description: HTTP status code.
            message:
                type: string
                description: Description for the error.
      503:
        description: At the moment the server cannot create more instances.
        schema:
            $ref: '#/definitions/Error'
    """
    # return "%r" % request.get_json()
    available_port = Port.allocate()

    if available_port is None:
        return unavailable(error="The server cannot create new instances. Please, wait and retry it.")

    # Create container with Docker
    vnc_port = available_port.number + 10000
    docker = Client(app.config['DOCKER_URL'], version='auto')
    port_bindings = { app.config['DOCKER_PT_PORT']: available_port.number,
                      app.config['DOCKER_VNC_PORT']: vnc_port }
    vol_bindings = { app.config['CACHE_DIR']:
                    {'bind': app.config['CACHE_CONTAINER_DIR'], 'mode': 'ro'} }
    host_config = docker.create_host_config(
                                port_bindings=port_bindings,
                                binds=vol_bindings,
                                volumes_from=(app.config['DOCKER_DATA_ONLY'],))
    container = docker.create_container(image=app.config['DOCKER_IMAGE'],
                                        ports=list(port_bindings.keys()),
                                        volumes=[vol_bindings[k]['bind'] for k in vol_bindings],
                                        host_config=host_config)
    if container.get('Warnings'):
        return internal_error('Error during container creation: %s' % container.get('Warnings'))

    # If success...
    response = docker.start(container=container.get('Id'))  # TODO log response?
    instance = Instance.create(container.get('Id'), available_port.number, vnc_port)
    available_port.assign(instance.id)

    # If sth went wrong: available_port.release()
    # Return appropriate HTTP errorv
    return jsonify(instance.serialize("%s/%d" % (request.base_url, instance.id), get_host()))


@app.route("/instances/<instance_id>", endpoint="v1_instance")
def show_instance_details_v1(instance_id):
    """
    Shows the details of a Packet Tracer instance.
    ---
    tags:
      - instance
    parameters:
      - name: instance_id
        in: path
        description: instance identifier
        required: true
        type: integer
    responses:
      200:
        description: Details of the instance
        schema:
            $ref: '#/definitions/Instance'
      404:
        description: There is not an instance for the given instance_id.
        schema:
            $ref: '#/definitions/Error'
    """
    instance = Instance.get(instance_id)
    if instance is None:
        return not_found(error="The instance does not exist.")
    return jsonify(instance.serialize(request.base_url, get_host()))


@app.route("/instances/<instance_id>", methods=['DELETE'], endpoint="v1_instance_delete")
def stop_instance_v1(instance_id):
    """
    Stops a running Packet Tracer instance.
    ---
    tags:
      - instance
    parameters:
      - name: instance_id
        in: path
        description: instance identifier
        required: true
        type: integer
    responses:
      200:
          description: Instance stopped
          schema:
              $ref: '#/definitions/Instance'
      404:
          description: There is not an instance for the given instance_id.
          schema:
              $ref: '#/definitions/Error'
    """
    instance = Instance.get(instance_id)
    if instance is None:
        return not_found(error="The instance does not exist.")
    docker = Client(app.config['DOCKER_URL'], version='auto')
    docker.stop(instance.docker_id)
    instance.stop()
    Port.get(instance.pt_port).release()  # The port can be now reused by a new PT instance
    return jsonify(instance.serialize(request.base_url, get_host()))


@app.route("/ports", endpoint="v1_ports")
def list_ports_v1():
    """
    Lists the ports used by the Packet Tracer instances.
    ---
    tags:
      - port
    parameters:
      - name: show
        in: query
        type: string
        description: Filter ports by their current status
        default: all
        enum: [all, available, unavailable]
    responses:
      200:
        description: Ports
        schema:
            properties:
                ports:
                    type: array
                    items:
                      id: Port
                      properties:
                        number:
                            type: integer
                            description: Number of port
                        used_by:
                            type: integer
                            description: Identifier of the instance currently using it or -1 if the port is available.
    """
    show_param = request.args.get("show")
    if show_param is None or show_param == "all":
        return jsonify(ports=[port.serialize for port in Port.get_all()])
    else:
        if show_param not in ("available", "unavailable"):
            return BadRequest("The 'show' parameter must contain one of the following values: all, available or unavailable.")

        if show_param == "available":
            return jsonify(ports=[port.serialize for port in Port.get_available()])
        else:  # show_param is "unavailable":
            return jsonify(ports=[port.serialize for port in Port.get_unavailable()])


@app.route("/files", endpoint="v1_files")
def list_cached_files():
    """
    Returns the files cached and the original URLs that they cache.
    ---
    tags:
      - file
    responses:
      200:
        description: Cached files.
        schema:
            properties:
                files:
                    type: array
                    items:
                      $ref: '#/definitions/File'
    """
    # list available files
    c_dir = app.config['CACHE_CONTAINER_DIR']
    return jsonify(files=[cached_file.serialize(c_dir) for cached_file in CachedFile.get_all()])


def delete_file(cached_file):
    try:
        os.remove(app.config['CACHE_DIR'] + cached_file.filename)
        CachedFile.delete(cached_file)
    except OSError as e:  # E.g., if the file does not exist.
        if e.errno==errno.ENOENT:
            # We wanted to delete it anyway so go ahead
            CachedFile.delete(cached_file)
        else: raise  # E.g., permission denied


@app.route("/files", methods=['DELETE'], endpoint="v1_files_delete")
def clear_cache():
    """
    Clears the cache of files.
    ---
    tags:
      - file
    responses:
      200:
        description: Cached files.
        schema:
            properties:
                files:
                    type: array
                    items:
                      $ref: '#/definitions/File'
      500:
        description: The file could not be deleted from the cache.
        schema:
            $ref: '#/definitions/Error'
    """
    deleted_files = []
    c_dir = app.config['CACHE_CONTAINER_DIR']
    for cached_file in CachedFile.get_all():
        try:
            delete_file(cached_file)  # TODO capture errors?
        except OSError as e:
            return internal_error(('Error during the file removal from the cache. %s. ' +
                                'The exception raised with the following file: %s') %
                                (e.strerror, cached_file.filename))
        deleted_files.append(cached_file.serialize(c_dir))
    return jsonify(files=deleted_files)


def get_and_update_cached_file(file_url):
    """Returns cached file for the given URL only if the file exists."""
    cached_file = CachedFile.get(file_url)
    if cached_file:
        # check if the file still exists and remove the object from the DB otherwise
        if os.path.isfile(app.config['CACHE_DIR'] + cached_file.filename):
            return cached_file
        CachedFile.delete(cached_file)  # else
    return None


@app.route("/files/<file_url>", endpoint="v1_file")
def get_cached_file(file_url):
    """
    Returns the details the cached file if it exists.
    ---
    tags:
      - file
    parameters:
      - name: file_url
        in: path
        description: URL of the file cached.
        required: true
        type: string
    responses:
      200:
        description: Packet Tracer file cached
        schema:
          id: File
          properties:
            url:
                type: string
                description: URL of the file cached.
            filename:
                type: string
                description: Path of the file in the containers.
      404:
        description: There is no file cached for the given URL.
        schema:
          $ref: '#/definitions/Error'
    """
    file_url = urllib.unquote(file_url)
    cached_file = get_and_update_cached_file(file_url)
    if cached_file is None:
        return not_found(error="The URL is not cached.")
    return jsonify(cached_file.serialize(app.config['CACHE_CONTAINER_DIR']))


# Source: http://stackoverflow.com/questions/2257441/random-string-generation-with-upper-case-letters-and-digits-in-python
def get_random_name(length=32):
    return ''.join(random.SystemRandom().choice(string.ascii_lowercase + string.digits) for _ in range(length)) + '.pkt'

# Install proxy in urllib2 (if it is set)
def get_proxy_config():
    el = {}
    env = os.environ
    if 'http_proxy' in env:
        el['http'] = env['http_proxy']
    elif 'HTTP_PROXY' in env:
        el['http'] = env['HTTP_PROXY']
    if 'https_proxy' in env:
        el['https'] = env['https_proxy']
    elif 'HTTPS_PROXY' in env:
        el['https'] = env['HTTPS_PROXY']
    return el

def configure_urllib2():
    conf = get_proxy_config()
    if conf:
        proxy = urllib2.ProxyHandler(conf)
        opener = urllib2.build_opener(proxy)
        urllib2.install_opener(opener)

@app.route("/files", methods=['POST'], endpoint="v1_file_cache")
def cache_file():
    """
    Caches a Packet Tracer file.
    ---
    tags:
      - file
    parameters:
      - name: file_url
        in: body
        description: URL of the file to be cached.
        required: true
        type: string
    responses:
      201:
        description: Packet Tracer file cached.
        schema:
            $ref: '#/definitions/File'
      400:
        description: The URL could not be accessed. It might not exist.
        schema:
            $ref: '#/definitions/Error'
    """
    file_url = request.data
    cached_file = get_and_update_cached_file(file_url)
    if cached_file:
        return  jsonify(cached_file.serialize(app.config['CACHE_CONTAINER_DIR']))
    # if not exist download and store
    filename = get_random_name()
    try:
        configure_urllib2()
        with open(app.config['CACHE_DIR'] + filename, 'w') as f:
            f.write(urllib2.urlopen(file_url).read())
            f.close()
    except IOError:
        return bad_request(error="The URL passed could not be reached. Is '%s' correct?" % file_url)
    new_cached = CachedFile.create(file_url, filename)
    return jsonify(new_cached.serialize(app.config['CACHE_CONTAINER_DIR']))


@app.route("/files/<file_url>", methods=['DELETE'], endpoint="v1_file_delete")
def delete_file_from_cache(file_url):
    """
    Clears file from the cache.
    ---
    tags:
      - file
    parameters:
      - name: file_url
        in: path
        description: URL of the file to be deleted from the cache.
        required: true
        type: string
    responses:
      201:
        description: Packet Tracer file deleted from the cache.
        schema:
            $ref: '#/definitions/File'
      404:
        description: There is no file cached for the given URL.
        schema:
            $ref: '#/definitions/Error'
    """
    file_url = urllib.unquote(file_url)
    cached_file = get_and_update_cached_file(file_url)
    if not cached_file:
        return not_found(error="The URL is not cached.")
    delete_file(cached_file)
    return  jsonify(cached_file.serialize(app.config['CACHE_CONTAINER_DIR']))
