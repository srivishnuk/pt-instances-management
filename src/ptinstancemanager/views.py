"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from urlparse import urlparse
from subprocess import check_output
from flask import redirect, request, render_template, url_for, jsonify
from werkzeug.exceptions import BadRequest
from ptinstancemanager.app import app
from ptinstancemanager.models import Instance, Port


@app.route("/")
def index():
    return redirect("/apidocs/index.html")


@app.errorhandler(404)
def not_found(error=None):
    message = {
        'status': 404,
        'message': 'Not Found: %s.\n%s' % (request.url, error),
    }
    resp = jsonify(message)
    resp.status_code = 404
    return resp


@app.errorhandler(503)
def unavailable(error=None):
    message = {
        'status': 503,
        'message': 'Service Unavailable: %s' % error,
    }
    resp = jsonify(message)
    resp.status_code = 503
    return resp


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
    """
    # return "%r" % request.get_json()
    available_port = Port.allocate()

    if available_port is None:
        return unavailable(error="The server cannot create new instances. Please, wait and retry it.")

    # Create container with Docker
    vnc_port = available_port.number + 10000
    command = "docker run -d -p %d:39000 -p %d:5900 -t -i %s" % (available_port.number, vnc_port, app.config['DOCKER_IMAGE'])
    container_id = check_output(command.split()).strip()
    # If success...
    instance = Instance.create(container_id, available_port.number, vnc_port)
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
    """
    instance = Instance.get(instance_id)
    if instance is None:
        return not_found(error="The instance does not exist.")
    command = "docker stop %s" % instance.docker_id
    output = check_output(command.split()).strip()  # TODO log the answer!
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
