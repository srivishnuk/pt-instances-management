"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

import os
import errno
import random
import string
import urllib2
import logging
from urlparse import urlparse
from flask import redirect, request, render_template, url_for, jsonify
from werkzeug.exceptions import BadRequest
from ptinstancemanager import tasks
from ptinstancemanager.app import app
from ptinstancemanager.models import Allocation, Instance, Port, CachedFile


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

def get_json_allocations(allocations):
    h = get_host()
    return jsonify(allocations=[al.serialize("%s/%d" % (request.base_url, al.id), h) for al in allocations])


@app.route("/allocations", endpoint="v1_allocations")
def list_allocations_v1():
    """
    Lists allocations.
    ---
    tags:
      - allocation
    parameters:
      - name: show
        in: query
        type: string
        description: Show different allocations
        default: current
        enum: [all, current, finished]
    responses:
      200:
        description: Allocations of Packet Tracer instances
        schema:
            properties:
                allocations:
                    type: array
                    items:
                      $ref: '#/definitions/Allocation'
    """
    show_param = request.args.get("show")
    if show_param is None or show_param == "current":  # default option
        return get_json_allocations(Allocation.get_current())
    else:
        if show_param not in ("all", "current", "finished"):
            return BadRequest("The 'show' parameter must contain one of the following values: all, running or finished.")

        if show_param == "all":
            return get_json_allocations(Allocation.get_all())  # .limit(10)
        else:  # show_param is "finished":
            return get_json_allocations(Allocation.get_finished())


@app.route("/allocations", methods=['POST'], endpoint="v1_allocation_create")
def allocate_instance_v1():
    """
    Allocates a Packet Tracer instance.
    ---
    tags:
        - allocation
    responses:
        201:
            description: Packet Tracer instance allocated (i.e., allocation created)
            schema:
                id: Allocation
                properties:
                    id:
                        type: integer
                        description: Identifier of the allocation
                    url:
                        type: string
                        description: URL to handle the allocation
                    packetTracer:
                        type: string
                        description: Host and port where the Packet Tracer instance can be contacted (through IPC)
                    createdAt:
                        type: string
                        format: date-time
                        description: When was the allocation created?
                    removedAt:
                        type: string
                        format: date-time
                        description: When was the allocation removed/stopped?
        500:
            description: The instance could not be allocated, there was an error.
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
            description: At the moment the server cannot allocate more instances.
            schema:
                $ref: '#/definitions/Error'
    """
    try:
        result = tasks.allocate_instance.delay()
        allocation_id = result.wait()
        if allocation_id:
            allocation = Allocation.get(allocation_id)
            return jsonify(allocation.serialize("%s/%d" % (request.base_url, allocation.id), get_host()))
        return unavailable()
    except Exception as e:
        return internal_error(e.args[0])


@app.route("/allocations/<allocation_id>", endpoint="v1_allocation")
def show_allocation_details_v1(allocation_id):
    """
    Shows the details of a Packet Tracer instance allocation.
    ---
    tags:
      - allocation
    parameters:
      - name: allocation_id
        in: path
        type: integer
        description: allocation identifier
        required: true
    responses:
      200:
        description: Details of the instance allocation.
        schema:
            $ref: '#/definitions/Allocation'
      404:
        description: There is not an allocation for the given allocation_id.
        schema:
            $ref: '#/definitions/Error'
    """
    allocation = Allocation.get(allocation_id)
    if allocation:
        return jsonify(allocation.serialize(request.base_url, get_host()))
    return not_found(error="The allocation does not exist.")


@app.route("/allocations/<allocation_id>", methods=['DELETE'], endpoint="v1_allocation_delete")
def deallocate_instance_v1(allocation_id):
    """
    Stops a running Packet Tracer instance.
    ---
    tags:
      - allocation
    parameters:
      - name: allocation_id
        in: path
        type: integer
        description: allocation identifier
        required: true
    responses:
      200:
          description: Allocation removed
          schema:
              $ref: '#/definitions/Allocation'
      404:
          description: There is not an allocation for the given allocation_id.
          schema:
              $ref: '#/definitions/Error'
    """
    instance = Instance.get_by_allocation_id(allocation_id)
    if instance is None:
        return not_found(error="The allocation does not exist.")

    try:
        allocation_id = instance.allocated_by
        result = tasks.deallocate_instance.delay(instance.id)
        result.wait()
        allocation = Allocation.get(allocation_id)
        if allocation:
            # TODO update instance object as status has changed
            return jsonify(allocation.serialize(request.base_url, get_host()))
        # else
        return not_found(error="The allocation does not exist.")
    except Exception as e:
        return internal_error(e.args[0])



def get_json_instances(instances):
    h = get_host()
    return jsonify(instances=[ins.serialize("%s/%d" % (request.base_url, ins.id), h) for ins in instances])


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
        enum: [all, starting, deallocated, allocated, running, finished, error]
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
    if show_param is None or show_param == "running":  # default option
        return get_json_instances(Instance.get_running())
    else:
        if show_param not in ("all", "starting", "unassigned", "assigned", "finished"):
            return BadRequest("The 'show' parameter must contain one of the following values: all, running or finished.")

        if show_param == "all":
            return get_json_instances(Instance.get_all())  # .limit(10)
        elif show_param == "starting":
            return get_json_instances(Instance.get_starting())
        elif show_param == "deallocated":
            return get_json_instances(Instance.get_deallocated())
        elif show_param == "allocated":
            return get_json_instances(Instance.get_allocated())
        elif show_param == "error":
            return get_json_instances(Instance.get_error())
        else:  # show_param is "finished":
            return get_json_instances(Instance.get_finished())


@app.route("/instances", methods=['POST'], endpoint="v1_instance_create")
def assign_instance_v1():
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
                    createdAt:
                        type: string
                        format: date-time
                        description: When was the instance created?
                    removedAt:
                        type: string
                        format: date-time
                        description: When was the instance removed/stopped?
                    status:
                		type: string
                        enum: [all, starting, deallocated, allocated, running, finished, error]
                	    description: Show status of the given instance
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
    try:
        result = tasks.create_container()
        instance_id = result.get()
        if instance_id:
            instance = Instance.get(instance_id)
            return jsonify(instance.serialize("%s/%d" % (request.base_url, instance.id), get_host()))
        return unavailable()
    except Exception as e:
        return internal_error(e.args[0])


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
        type: integer
        description: instance identifier
        required: true
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
def delete_instance_v1(instance_id):
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

    try:
        result = tasks.remove_container.delay(instance.docker_id)
        result.wait()
        instance.delete()
        # TODO update instance object as status has changed
        return jsonify(instance.serialize(request.base_url, get_host()))
    except Exception as e:
        return internal_error(e.args[0])


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
        with open(app.config['CACHE_DIR'] + filename, 'w') as f:
            f.write(urllib2.urlopen(file_url).read())
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
