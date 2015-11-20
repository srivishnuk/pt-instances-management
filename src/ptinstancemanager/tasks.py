import logging
from docker import Client
from docker.errors import APIError
from celery import chain

import ptchecker
from ptinstancemanager.app import app, celery
from ptinstancemanager.models import Instance, Port, CachedFile



def create_containers(num_containers):
    logging.info('Creating new containers.')
    for _ in range(num_containers):
        available_port = Port.allocate()

        if available_port is None:
            raise Exception('The server cannot create new instances. Please, wait and retry it.')

        res = create_container.apply_async((available_port.number,), link=wait_for_ready_container.s(10))


@celery.task()
def create_container(pt_port):
    logging.info('Creating new container.')

    # Create container with Docker
    vnc_port = pt_port + 10000
    container_id = start_container(pt_port, vnc_port)

    # If success...
    instance = Instance.create(container_id, pt_port, vnc_port)
    port = Port.get(pt_port)
    port.assign(instance.id)

    logging.info('Container started: %s' % container_id)

    return instance.id


#@celery.task()
def start_container(pt_port, vnc_port):
    """Create container with Docker."""
    docker = Client(app.config['DOCKER_URL'], version='auto')
    port_bindings = { app.config['DOCKER_PT_PORT']: pt_port,
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
        raise Exception('Error during container creation: %s' % container.get('Warnings'))

    # If success...
    response = docker.start(container=container.get('Id'))  # TODO log response?

    return container.get('Id')


@celery.task()
def stop_container(instance_id):
    instance = Instance.get(instance_id)
    docker = Client(app.config['DOCKER_URL'], version='auto')
    try:
        docker.stop(instance.docker_id)
	instance.stop()
	Port.get(instance.pt_port).release()  # The port can be now reused by a new PT instance
    except APIError as ae:
         # if it was already stopped or removed
	if cli.containers(filters={'status': 'exited'}):  # Not empty array
	    instance.stop()
	    Port.get(instance.pt_port).release()  # The port can be now reused by a new PT instance


@celery.task()
def assign_container():
    logging.info('Assigning container.')
    docker = Client(app.config['DOCKER_URL'], version='auto')
    for instance in Instance.get_unassigned():
	try:
	    docker.unpause(instance.docker_id)
	    instance.assign()
            return instance.id
        except APIError as ae:
	    # e.g., if it was already unpaused or it has been stopped
	    instance.mark_error()
	    logging.error('Docker API exception. %s.' % ae)


@celery.task()
def unassign_container(instance_id):
    instance = Instance.get(instance_id)
    docker = Client(app.config['DOCKER_URL'], version='auto')
    try:
        docker.pause(instance.docker_id)
    except APIError as ae:
	# e.g., if it was already paused
	instance.mark_error()
        logging.error('Docker API exception. %s.' % ae)
    finally:
        instance.unassign()


@celery.task(max_retries=5)
def wait_for_ready_container(instance_id, timeout):
    logging.info('Waiting for container to be ready.')
    instance = Instance.get(instance_id)
    is_running = ptchecker.is_running(app.config['PT_CHECKER'], 'localhost', instance.pt_port, float(timeout))
    if not is_running:
    	# TODO mark as an error after all the retries
	raise wait_for_ready_container.retry(exc=Exception('The container has not answered yet.'))
    unassign_container.delay(instance_id)  # else
