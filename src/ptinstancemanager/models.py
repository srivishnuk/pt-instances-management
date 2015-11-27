"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from datetime import datetime
from sqlalchemy.types import NullType
from ptinstancemanager.app import db


class Allocation(db.Model):
    __tablename__ = 'allocation'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    deleted_at = db.Column(db.DateTime)

    def __repr__(self):
        return '<Allocation %r>' % self.id

    def __str__(self):
        return 'Allocation-%r' % self.id

    def is_active(self):
        return self.deleted_at is None # check if deletion time is set

    def delete(self):
        self.deleted_at = datetime.now()  # set deletion time
        db.session.commit()

    def serialize(self, url, local_machine):
        """Return object data in easily serializeable format"""
        pt_value = None
        if self.is_active():
            el = Instance.get_by_allocation_id(self.id)
            if el:
                pt_value = "%s:%d" % (local_machine, el.pt_port)
        return {
            'id': self.id,
            'url': url,
            'packetTracer': pt_value,
            'createdAt': self.created_at.isoformat(),
            'deletedAt': self.deleted_at.isoformat() if self.deleted_at else None
        }

    @staticmethod
    def create():
        allocation = Allocation()
        db.session.add(allocation)
        db.session.commit()
        return allocation

    @staticmethod
    def get(allocation_id):
        return db.session.query(Allocation).filter_by(id=allocation_id).first()

    @staticmethod
    def get_all():
        return db.session.query(Allocation).all()

    @staticmethod
    def get_current():
        return db.session.query(Allocation).filter_by(deleted_at = None)

    @staticmethod
    def get_finished():
        return db.session.query(Allocation).filter(Allocation.deleted_at != None).all()


class Instance(db.Model):
    ERROR = -3  # Status to be rechecked on docker (stopped, in an unexpected state...)
    STARTING = -2
    READY = -1
    NONE = -1
    __tablename__ = 'instance'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    docker_id = db.Column(db.String)
    pt_port = db.Column(db.Integer)
    vnc_port = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now)
    deleted_at = db.Column(db.DateTime)
    allocated_by = db.Column(db.Integer, default=NONE)
    status = db.Column(db.Integer, default=STARTING)

    def __init__(self, docker_id, pt_port, vnc_port):
        self.docker_id = docker_id
        self.pt_port = pt_port
        self.vnc_port = vnc_port

    def __repr__(self):
        return '<Instance %r>' % self.id

    def __str__(self):
        return 'Instance-%r' % self.id

    def is_active(self):
        return self.deleted_at is None # check if deletion time is set

    def is_allocated(self):
        return self.allocated_by!=Instance.NONE

    def allocate(self):
        if self.is_allocated():
            # Return already existing one
            return Allocation.get(self.allocated_by)
        else:
            ret = Allocation.create()
            self.allocated_by = ret.id
            db.session.commit()
            return ret

    def deallocate(self):
        if self.is_allocated():
            allocation = Allocation.get(self.allocated_by)
            allocation.delete()
            self.allocated_by = Instance.NONE
            db.session.commit()

    def mark_starting(self):
        self.status = Instance.STARTING
        db.session.commit()

    def mark_ready(self):
        self.status = Instance.READY
        db.session.commit()

    def mark_error(self):
        self.status = Instance.ERROR
        db.session.commit()

    def delete(self):
        self.deallocate()
        self.deleted_at = datetime.now()  # set deletion time
        db.session.commit()
        Port.get(self.pt_port).release()

    def get_id(self):
        return self.id

    def get_status(self):
        if self.is_active():
            if self.status == Instance.STARTING:
                return "starting"
            elif self.status == Instance.ERROR:
                return "error"
            #elif self.status == Instance.READY:
            return "allocated" if self.is_allocated() else "deallocated"
        else:
            return "finished"

    def serialize(self, url, local_machine):
       """Return object data in easily serializeable format"""
       return {
            'id': self.id,
            'url': url,
            'dockerId': self.docker_id,
            'packetTracer': "%s:%d" % (local_machine, self.pt_port),
            'vnc': "vnc://%s:%d" % (local_machine, self.vnc_port),
            'createdAt': self.created_at.isoformat(),
            'deletedAt': self.deleted_at.isoformat() if self.deleted_at else None,
            'status': self.get_status()
       }

    @staticmethod
    def create(docker_id=None, pt_port=None, vnc_port=None):
        instance = Instance(docker_id, pt_port, vnc_port)
        db.session.add(instance)
        db.session.commit()
        return instance

    @staticmethod
    def get(instance_id):
        return db.session.query(Instance).filter_by(id = instance_id).first()

    @staticmethod
    def get_by_docker_id(docker_id):
        return db.session.query(Instance).filter_by(docker_id = docker_id).first()

    @staticmethod
    def get_by_allocation_id(allocation_id):
        return db.session.query(Instance).filter_by(allocated_by = allocation_id).first()

    @staticmethod
    def get_all():
        return db.session.query(Instance).all()

    @staticmethod
    def get_running():
        return db.session.query(Instance).filter_by(deleted_at = None)

    @staticmethod
    def get_finished():
        return db.session.query(Instance).filter(Instance.deleted_at != None).all()

    @staticmethod
    def get_erroneous():
        return db.session.query(Instance).filter_by(deleted_at = None, status = Instance.ERROR)

    @staticmethod
    def get_starting():
        return db.session.query(Instance).filter_by(deleted_at = None, status = Instance.STARTING)

    @staticmethod
    def get_deallocated():
        return db.session.query(Instance).\
                filter(Instance.deleted_at == None).\
                filter(Instance.allocated_by == Instance.NONE).\
                filter(Instance.status != Instance.ERROR).\
                order_by( Instance.status.desc() )  # First READY, then STARTING

    @staticmethod
    def get_allocated():
        return db.session.query(Instance).filter(Instance.deleted_at == None, Instance.allocated_by != Instance.NONE)



class Port(db.Model):
    UNASSIGNED = -2
    ALLOCATED = -1
    __tablename__ = 'port'
    number = db.Column(db.Integer, primary_key=True, autoincrement=False)
    # not using db.relationship intentionally. I don't want to keep the other reference.
    instance_id = db.Column(db.Integer, default=UNASSIGNED)

    def __init__(self, port_number):
        self.number = port_number

    def __repr__(self):
        return '<Port %r>' % self.number

    def __str__(self):
        return 'Port-%r' % self.number

    def __set_used_by(self, instance_id=None):
        self.instance_id = instance_id if instance_id else Port.UNASSIGNED

    def assign(self, assigned_instance_id):
        assert assigned_instance_id not in (None, Port.UNASSIGNED, Port.ALLOCATED)
        self.__set_used_by(assigned_instance_id)
        db.session.commit()

    def release(self):
        self.__set_used_by(None)
        db.session.commit()

    @property
    def serialize(self):
       """Return object data in easily serializeable format"""
       return {
            'number': self.number,
            'used_by': self.instance_id
       }

    @staticmethod
    def get(port_number):
        return db.session.query(Port).filter_by(number = port_number).first()

    @staticmethod
    def get_all():
        return db.session.query(Port).all()

    @staticmethod
    def get_available():
        return db.session.query(Port).filter_by(instance_id = Port.UNASSIGNED)

    @staticmethod
    def get_unavailable():
        return db.session.query(Port).filter(Port.instance_id != Port.UNASSIGNED)

    @staticmethod
    def allocate():
        allocated_port = Port.get_available().first()
        if allocated_port is not None:
            allocated_port.__set_used_by(Port.ALLOCATED)
            db.session.commit()
        return allocated_port



class CachedFile(db.Model):
    __tablename__ = 'cached'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    url = db.Column(db.String, index=True, unique=True)
    filename = db.Column(db.String, unique=True)

    def __init__(self, url, local_filename):
        self.url = url
        self.filename = local_filename

    def __repr__(self):
        return '<CachedFile %r: %r>' % (self.url, self.filename)

    def __str__(self):
        return 'CachedFile %r: %r' % (self.url, self.filename)

    def serialize(self, container_mount_dir):
       """Return object data in easily serializeable format"""
       return {
            'url': self.url,
            'filename': container_mount_dir + self.filename
       }

    @staticmethod
    def create(url, local_filename):
        cached_file = CachedFile(url, local_filename)
        db.session.add(cached_file)
        db.session.commit()
        return cached_file

    @staticmethod
    def get(url):
        return db.session.query(CachedFile).filter_by(url=url).first()

    @staticmethod
    def get_all():
        return db.session.query(CachedFile).all()

    @staticmethod
    def delete(cached_file):
        db.session.delete(cached_file)
        db.session.commit()



def init_database(dbase, lowest_port, highest_port):
    for port_number in range(lowest_port, highest_port+1):
        available_port = Port(port_number)
        db.session.add(available_port)
    db.session.commit()
