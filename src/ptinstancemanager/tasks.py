import re
import psutil
import logging
from functools import wraps

from docker import Client
from docker.errors import APIError
from celery import chain
from celery.exceptions import MaxRetriesExceededError

import ptchecker
from ptinstancemanager.app import app, celery
from ptinstancemanager.models import Instance, Port, CachedFile
from ptinstancemanager.exceptions import InsufficientResourcesError, DockerContainerError


# To make sure that Celery tasks use this logger too...
logger = logging.getLogger()


def cancellable(check=('cpu', 'memory')):
    def cancellable_decorator(func):
        @wraps(func)
        def has_enough_resources(*args, **kwargs):
            """Has the machine reached the CPU consumption threshold?"""
            if 'memory' in check:
                max_memory = app.config['MAXIMUM_MEMORY']
                current = psutil.virtual_memory().percent
                if current >= max_memory:
                    raise InsufficientResourcesError('Operation cancelled: not enough Memory. Currently using: %.2f%%.' % current)

            if 'cpu' in check:
                max_cpu = app.config['MAXIMUM_CPU']
                # It is recommended for accuracy that this function be called
                # with at least 0.1 seconds between calls.
                current = psutil.cpu_percent(interval=0.1)  #  Blocked during 0.1 secs
                if current >= max_cpu:
                    raise InsufficientResourcesError('Operation cancelled: not enough CPU. Currently using: %.2f%%.' % current)

            logger.info('All the thresholds were passed.')
            return func(*args, **kwargs)
        return has_enough_resources
    return cancellable_decorator


def create_instances(num_containers):
    logger.info('Creating new containers.')
    for _ in range(num_containers):
        create_instance.delay()


def allocate_port():
    available_port = Port.allocate()
    if available_port is None:
        raise InsufficientResourcesError('The server cannot create new instances. Please, wait and retry it.')
    return available_port


def get_docker_client():
    return Client(app.config['DOCKER_URL'], version='auto')


#@celery.task()
def start_container(pt_port, vnc_port):
    """Creates and starts new packettracer container with Docker."""
    docker = get_docker_client()
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
        raise DockerContainerError('Error during container creation: %s' % container.get('Warnings'))

    # If success...
    response = docker.start(container=container.get('Id'))  # TODO log response?

    return container.get('Id')


@celery.task()
def create_instance():
    """Runs a new packettracer container in the specified port and
        create associated instance."""
    logger.info('Creating new container.')
    pt_port = allocate_port()
    vnc_port_number = pt_port.number + 10000
    try:
        container_id = start_container(pt_port.number, vnc_port_number)
        logger.info('Container started: %s' % container_id)

        # If success...
        instance = Instance.create(container_id, pt_port.number, vnc_port_number)
        pt_port.assign(instance.id)

        wait_for_ready_container.s(instance.id).delay()
        return instance.id
    except DockerContainerError as e:
        pt_port.release()
        raise e


@celery.task()
@cancellable()
#@cancellable(check=('cpu',))  # Check only the CPU threshold
def allocate_instance():
    """Unpauses available container and marks associated instance as allocated."""
    logger.info('Allocating instance.')
    docker = get_docker_client()

    error_discovered = False
    allocation_id = None
    for instance in Instance.get_deallocated():
        try:
            docker.unpause(instance.docker_id)
            allocation_id = instance.allocate().id
            break
        except APIError as ae:
            logger.error('Error allocating instance %s.' % instance.id)
            logger.error('Docker API exception. %s.' % ae)
            # e.g., if it was already unpaused or it has been stopped
            instance.mark_error()

    if not allocation_id:
        # If there were no instances available, consider the creation of a new one
        instance_id = create_instance.s()()  # Execute task inline
        allocation_id = Instance.get(instance_id).allocate().id

    return allocation_id


@celery.task()
def deallocate_instance(instance_id):
    """Marks instance as deallocated and pauses the associated container."""
    logger.info('Deallocating instance %s.' % instance_id)
    instance = Instance.get(instance_id)
    try:
        docker = get_docker_client()
        docker.pause(instance.docker_id)
        instance.deallocate()
    except APIError as ae:
        logger.error('Error deallocating instance %s.' % instance_id)
        logger.error('Docker API exception. %s.' % ae)
        # e.g., if it was already paused
        instance.mark_error()


def is_container_running(container_id):
    try:
        docker = get_docker_client()
        return docker.inspect_container(container_id)['State']['Running']
    except APIError as ae:
        logger.error('Error checking container status: ' + container_id)
        logger.error('Docker API exception. %s.' % ae)
        return False


# Worst case tested scenario has been 15 seconds,
# so if in 38 seconds (4*2 + 3*10) it has not answered,
# we can consider the container erroneous.
@celery.task(max_retries=3, default_retry_delay=10)
# Once it is ready, the container uses to answer in less than 200 ms.
# Therefore a timeout of 2 seconds should be enough to know whether it is ready.
def wait_for_ready_container(instance_id, timeout=2):
    """Waits for an instance to be ready (e.g., answer).
        Otherwise, marks it as erroneous ."""
    logger.info('Waiting for container to be ready.')
    instance = Instance.get(instance_id)
    container_running = is_container_running(instance.docker_id)
    if container_running:
        is_running = ptchecker.is_running(app.config['PT_CHECKER'], 'localhost', instance.pt_port, float(timeout))
        if is_running:
            instance.mark_ready()
            if not instance.is_allocated():
                # TODO rename the following task as it sounds confusing.
                # We call it here to pause the instance, not to "deallocate it".
                deallocate_instance.s(instance_id).delay()
        else:
            try:
                raise wait_for_ready_container.retry()
            except MaxRetriesExceededError:
                instance.mark_error()
    else:
        # If the container is not even running, PT won't answer no matter
        # how many times we try...
        instance.mark_error()
    return instance_id


@celery.task()
def try_restart_on_exited_containers():
    docker = get_docker_client()
    restarted_instances = []
    # 'exited': 0 throws exception, 'exited': '0' does not work.
    # Because of this I have felt forced to use regular expressions :-(
    pattern = re.compile(r"Exited [(](\d+)[)]")
    for container in docker.containers(filters={'status': 'exited'}):
        # Ignore containers not created from image 'packettracer'
        if container.get('Image')=='packettracer':
            match = pattern.match(container.get('Status'))
            if match:  # Stopped containers only
                container_id = container.get('Id')
                instance = Instance.get_by_docker_id(container_id)
                if instance:
                    if match.group(1)=='0':
                        # Restart stopped containers (which exited successfully)
                        instance.mark_starting()
                        try:
                            logger.info('Restarting %s.' % instance)
                            docker.start(container=container_id)
                            wait_for_ready_container.s(instance.id).delay()
                            restarted_instances.append(instance.id)
                        except APIError as ae:
                            logger.error('Error restarting container.')
                            logger.error('Docker API exception. %s.' % ae)
                            instance.mark_error()
                    else:
                        # TODO Check more thoroughly if containers with other
                        # type of exit errors could be restarted too.
                        instance.mark_error()
    return restarted_instances


@celery.task()
def delete_erroneous(not_delete=[]):
    deleted_instances = []
    for erroneous_instance in Instance.get_erroneous():
        if erroneous_instance.id not in not_delete:
            logger.info('Deleting erroneous %s.' % erroneous_instance)
            erroneous_instance.delete()
            deleted_instances.append(erroneous_instance.id)
            # Very conservative approach:
            #   we remove it even if it might still be usable.
            remove_container.s(erroneous_instance.docker_id).delay()
    return deleted_instances


@celery.task()
# This is a sort of mix between a Garbage collector and a Supervisor daemon :-P
def monitor_containers():
    logger.info('Monitoring instances.')
    chain(try_restart_on_exited_containers.s(), delete_erroneous.s())()


@celery.task()
def remove_container(docker_id):
    logger.info('Removing container %s.' % docker_id)
    docker = get_docker_client()
    try:
        state = docker.inspect_container(docker_id)['State']
        if state['Paused']:
            docker.unpause(docker_id)
        # It might be 'Running' or all to false (exited)
        docker.remove_container(docker_id, force=True)
    except APIError as ae:
        logger.error('Error on container removal: %s.' % docker_id)
        logger.error('Docker API exception. %s.' % ae)
