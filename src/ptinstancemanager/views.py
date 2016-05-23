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
from celery.exceptions import TaskRevokedError
from werkzeug.exceptions import BadRequest
from ptinstancemanager import tasks
from ptinstancemanager.app import app
from ptinstancemanager.models import Allocation, Instance, Port, CachedFile
from ptinstancemanager.exceptions import InsufficientResourcesError, DockerContainerError


@app.route("/")
def index():
    return redirect("/apidocs/index.html")

def get_json_error(error_number, message):
    resp = jsonify({ 'status': error_number, 'message': message })
    resp.status_code = error_number
    return resp

@app.errorhandler(400)
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


@app.route("/details")
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
                    maximum_cpu:
                        type: integer
                        format: float
                        description: Threshold of CPU usage percentage
                    maximum_memory:
                        type: integer
                        format: float
                        description: Threshold of memory usage percentage
                    lowest_port:
                        type: integer
                        description: minimum port for newly created instances
                    highest_port:
                        type: integer
                        description: maximum port for newly created instances
    """
    return jsonify( maximum_cpu=app.config['MAXIMUM_CPU'],
                    maximum_memory=app.config['MAXIMUM_MEMORY'],
                    lowest_port=app.config['LOWEST_PORT'],
                    highest_port=app.config['HIGHEST_PORT'] )


def get_host():
    return urlparse(request.base_url).hostname

def get_json_allocations(allocations):
    h = get_host()
    return jsonify(allocations=[al.serialize("%s/%d" % (request.base_url, al.id), h) for al in allocations])


@app.route("/allocations")
def list_allocations():
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
                      $ref: '#/definitions/allocate_instance_post_Allocation'
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


@app.route("/allocations", methods=['POST'])
def allocate_instance():
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
                    deletedAt:
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
                $ref: '#/definitions/allocate_instance_post_Error'
    """
    try:
        result = tasks.allocate_instance.apply_async()
        allocation_id = result.get()
        if allocation_id:
            allocation = Allocation.get(allocation_id)
            return jsonify(allocation.serialize("%s/%d" % (request.base_url, allocation.id), get_host()))
        return unavailable()
    except TaskRevokedError:
        return unavailable('timeout got during instance allocation')
    except InsufficientResourcesError as ire:
        return unavailable(ire.args[0])
    except DockerContainerError as e:
        return internal_error(e.args[0])


@app.route("/allocations/<allocation_id>")
def show_allocation_details(allocation_id):
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
            $ref: '#/definitions/allocate_instance_post_Allocation'
      404:
        description: There is not an allocation for the given allocation_id.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
    """
    allocation = Allocation.get(allocation_id)
    if allocation:
        return jsonify(allocation.serialize(request.base_url, get_host()))
    return not_found(error="The allocation does not exist.")


@app.route("/allocations/<allocation_id>", methods=['DELETE'])
def deallocate_instance(allocation_id):
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
              $ref: '#/definitions/allocate_instance_post_Allocation'
      404:
          description: There is not an allocation for the given allocation_id.
          schema:
              $ref: '#/definitions/allocate_instance_post_Error'
    """
    instance = Instance.get_by_allocation_id(allocation_id)
    if not instance:
        return not_found(error="The allocation does not exist.")

    try:
        allocation_id = instance.allocated_by
        result = tasks.deallocate_instance.apply_async(args=(instance.id,))
        result.get()
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


@app.route("/instances")
def list_instances():
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
                      $ref: '#/definitions/assign_instance_post_Instance'
    """
    show_param = request.args.get("show")
    if show_param is None or show_param == "running":  # default option
        return get_json_instances(Instance.get_running())
    else:
        states = ("all", "starting", "deallocated", "allocated", "running", "finished", "error")
        if show_param not in states:
            state_enum = "["
            for s in states:
                state_enum += "%s, " % s
            state_enum = state_enum[:-2] + "]"
            return BadRequest("The 'show' parameter must contain one of the following values: %s." % state_enum)

        if show_param == "all":
            return get_json_instances(Instance.get_all())  # .limit(10)
        elif show_param == "starting":
            return get_json_instances(Instance.get_starting())
        elif show_param == "deallocated":
            return get_json_instances(Instance.get_deallocated())
        elif show_param == "allocated":
            return get_json_instances(Instance.get_allocated())
        elif show_param == "error":
            return get_json_instances(Instance.get_erroneous())
        else:  # show_param is "finished":
            return get_json_instances(Instance.get_finished())


@app.route("/instances", methods=['POST'])
def assign_instance():
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
                    deletedAt:
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
                $ref: '#/definitions/allocate_instance_post_Error'
        503:
            description: At the moment the server cannot create more instances.
            schema:
                $ref: '#/definitions/allocate_instance_post_Error'
    """
    try:
        result = tasks.create_instance.delay()
        instance_id = result.get()
        if instance_id:
            instance = Instance.get(instance_id)
            return jsonify(instance.serialize("%s/%d" % (request.base_url, instance.id), get_host()))
        return unavailable()
    except DockerContainerError as e:
        return internal_error(e.args[0])


@app.route("/instances/<instance_id>")
def show_instance_details(instance_id):
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
            $ref: '#/definitions/assign_instance_post_Instance'
      404:
        description: There is not an instance for the given instance_id.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
    """
    instance = Instance.get(instance_id)
    if instance is None:
        return not_found(error="The instance does not exist.")
    return jsonify(instance.serialize(request.base_url, get_host()))


@app.route("/instances/<instance_id>", methods=['DELETE'])
def delete_instance(instance_id):
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
              $ref: '#/definitions/assign_instance_post_Instance'
      404:
          description: There is not an instance for the given instance_id.
          schema:
              $ref: '#/definitions/allocate_instance_post_Error'
      503:
          description: The instance has not been deleted in the given time.
          schema:
              $ref: '#/definitions/allocate_instance_post_Error'
    """
    instance = Instance.get(instance_id)
    if not instance or not instance.is_active():
        return not_found(error="The instance does not exist.")

    result = tasks.remove_container.delay(instance.docker_id)
    result.get()
    instance.delete()
    # TODO update instance object as status has changed
    return jsonify(instance.serialize(request.base_url, get_host()))


@app.route("/ports")
def list_ports():
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


@app.route("/files")
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
                      $ref: '#/definitions/get_cached_file_get_File'
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


@app.route("/files", methods=['DELETE'])
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
                      $ref: '#/definitions/get_cached_file_get_File'
      500:
        description: The file could not be deleted from the cache.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
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


@app.route("/files/<path:file_url>")
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
          $ref: '#/definitions/allocate_instance_post_Error'
    """
    cached_file = get_and_update_cached_file(file_url)
    if not cached_file:
        return not_found(error="The URL is not cached.")
    return jsonify(cached_file.serialize(app.config['CACHE_CONTAINER_DIR']))


# Source: http://stackoverflow.com/questions/2257441/random-string-generation-with-upper-case-letters-and-digits-in-python
def get_random_name(length=32):
    return ''.join(random.SystemRandom().choice(string.ascii_lowercase + string.digits) for _ in range(length)) + '.pkt'


@app.route("/files", methods=['POST'])
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
            $ref: '#/definitions/get_cached_file_get_File'
      400:
        description: The URL could not be accessed. It might not exist.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
      500:
        description: The body of the request was incorrect. Please provide a valid file URL.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
    """
    file_url = request.data
    if not file_url:
        return internal_error('Empty body.')

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
    except ValueError:
        return internal_error('Invalid URL passed in the body.')

    new_cached = CachedFile.create(file_url, filename)
    return jsonify(new_cached.serialize(app.config['CACHE_CONTAINER_DIR']))


@app.route("/files/<path:file_url>", methods=['DELETE'])
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
            $ref: '#/definitions/get_cached_file_get_File'
      404:
        description: There is no file cached for the given URL.
        schema:
            $ref: '#/definitions/allocate_instance_post_Error'
    """
    cached_file = get_and_update_cached_file(file_url)
    if not cached_file:
        return not_found(error="The URL is not cached.")
    delete_file(cached_file)
    return  jsonify(cached_file.serialize(app.config['CACHE_CONTAINER_DIR']))
