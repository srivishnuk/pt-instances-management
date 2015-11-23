import re
import logging
from docker import Client
from docker.errors import APIError
from celery import chain

import ptchecker
from ptinstancemanager.app import app, celery
from ptinstancemanager.models import Instance, Port, CachedFile


# To make sure that Celery tasks use this logger too...
logger = logging.getLogger()


def create_containers(num_containers):
    logger.info('Creating new containers.')
    for _ in range(num_containers):
        available_port = Port.allocate()

        if available_port is None:
            raise Exception('The server cannot create new instances. Please, wait and retry it.')

        res = create_container.apply_async((available_port.number,), link=wait_for_ready_container.s())


@celery.task()
def create_container(pt_port):
    """Runs a new packettracer container in the specified port and
        create associated instance."""
    logger.info('Creating new container.')

    # Create container with Docker
    vnc_port = pt_port + 10000
    container_id = start_container(pt_port, vnc_port)

    # If success...
    instance = Instance.create(container_id, pt_port, vnc_port)
    port = Port.get(pt_port)
    port.assign(instance.id)

    logger.info('Container started: %s' % container_id)

    return instance.id


#@celery.task()
def start_container(pt_port, vnc_port):
    """Creates and starts new packettracer container with Docker."""
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
def assign_container():
    """Unpauses available container and marks associated instance as assigned."""
    logger.info('Assigning instance.')
    docker = Client(app.config['DOCKER_URL'], version='auto')
    for instance in Instance.get_unassigned():
    	try:
    	    docker.unpause(instance.docker_id)
    	    instance.assign()
            return instance.id
        except APIError as ae:
            logger.error('Error assigning instance %s.' % instance.id)
            logger.error('Docker API exception. %s.' % ae)
    	    # e.g., if it was already unpaused or it has been stopped
    	    instance.mark_error()
            monitor_containers.s().delay()


@celery.task()
def unassign_container(instance_id):
    """Marks instance as unassigned and pauses the associated container."""
    logger.info('Unassigning instance %s.' % instance_id)
    instance = Instance.get(instance_id)
    docker = Client(app.config['DOCKER_URL'], version='auto')
    try:
        docker.pause(instance.docker_id)
        instance.unassign()
    except APIError as ae:
        logger.error('Error unassigning instance %s.' % instance_id)
        logger.error('Docker API exception. %s.' % ae)
    	# e.g., if it was already paused
    	instance.mark_error()
        monitor_containers.s().delay()


@celery.task(max_retries=5)
def wait_for_ready_container(instance_id, timeout=30):
    """Waits for an instance to be ready (e.g., answer).
        Otherwise, marks it as erroneous ."""
    logger.info('Waiting for container to be ready.')
    instance = Instance.get(instance_id)
    is_running = ptchecker.is_running(app.config['PT_CHECKER'], 'localhost', instance.pt_port, float(timeout))
    if is_running:
        unassign_container.s(instance_id).delay()  # else
    else:
        instance.mark_error()
        monitor_containers.s().delay()
	    # raise wait_for_ready_container.retry(exc=Exception('The container has not answered yet.'))


@celery.task()
# This is a sort of mix between a Garbage collector and a Supervisor daemon :-P
def monitor_containers():
    logger.info('Monitoring instances.')
    restarted_instances = []
    docker = Client(app.config['DOCKER_URL'], version='auto')
    try:
        # 'exited': 0 throws exception, 'exited': '0' does not work.
        # Because of this I have felt forced to use regular expressions :-(
        pattern = re.compile(r"Exited [(](\d+)[)]")
    	for container in docker.containers(filters={'status': 'exited'}):
            # Ignore containers not created from image 'packettracer'
            if container.get('Image')=='packettracer':
                match = pattern.match(container.get('Status'))
                if match and match.group(1)=='0':
                    # Restart stopped containers (which exited successfully)
                    container_id = container.get('Id')
                    instance = Instance.get_by_docker_id(container_id)
                    if instance:
                        logger.info('Restarting %s.' % instance)
                        restarted_instances.append(instance.id)
                        instance.mark_starting()
                        docker.start(container=container_id)
                        wait_for_ready_container.s(instance_id).delay()

        for erroneous_instance in Instance.get_errors():
            if not erroneous_instance.docker_id in restarted_instances:
                logger.info('Deleting erroneous %s.' % instance)
                instance.delete()
            	Port.get(instance.pt_port).release()
                # Very conservative approach:
                #   we remove it even if it might still be usable.
                remove_container.s(erroneous_instance.docker_id).delay()
                # TODO replace erroneous instance with a new one?
    except APIError as ae:
        logger.error('Error on container monitoring.')
        logger.error('Docker API exception. %s.' % ae)
    finally:
        return restarted_instances



@celery.task()
def remove_container(docker_id):
    logger.info('Removing container %s.' % docker_id)
    docker = Client(app.config['DOCKER_URL'], version='auto')
    try:
        # TODO first check its status and then act? (e.g., to unpause it before)
        docker.remove_container(docker_id, force=True)
    except APIError as ae:
        logger.error('Error on container removal: %s.' % docker_id)
        logger.error('Docker API exception. %s.' % ae)
