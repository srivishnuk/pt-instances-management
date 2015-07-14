"""
Created on 13/07/2015

@author: Aitor Gomez Goiri <aitor.gomez-goiri@open.ac.uk>
"""

from datetime import datetime
from sqlalchemy.types import NullType
from ptinstancemanager.app import db


class Instance(db.Model):
    __tablename__ = 'instance'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pt_port = db.Column(db.Integer)
    vnc_port = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now)
    deleted_at = db.Column(db.DateTime)

    def __init__(self, pt_port):
        self.pt_port = pt_port

    def __repr__(self):
        return '<Instance %r>' % self.id

    def __str__(self):
        return 'Instance-%r' % self.id

    def is_active(self):
        return self.deleted_at is None # check if deletion time is set

    def delete(self):
        # set deletion time
	   self.deleted_at = datetime.now()

    def get_id(self):
        return self.id

    @property
    def serialize(self):
       """Return object data in easily serializeable format"""
       return {
            'id': self.id,
            'port': self.pt_port,
            'vnc': self.vnc_port,
            'created_at': self.created_at.isoformat(),
            'removed_at': self.deleted_at.isoformat() if self.deleted_at else None
       }

    @staticmethod
    def create(pt_port=None):
        instance = Instance(pt_port)
        db.session.add(instance)
        db.session.commit()
        return instance

    @staticmethod
    def stop(instance_id):
        instance = Instance.get(instance_id)
        if instance is not None:
            instance.delete()
            db.session.commit()
        return instance

    @staticmethod
    def get(instance_id):
        return db.session.query(Instance).filter_by(id = instance_id).first()

    @staticmethod
    def get_all():
        return db.session.query(Instance).all()

    @staticmethod
    def get_running():
        return db.session.query(Instance).filter_by(deleted_at = None)

    @staticmethod
    def get_finished():
        return db.session.query(Instance).filter(Instance.deleted_at != None).all()



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
        self.instance_id = Port.UNASSIGNED if instance_id is None else instance_id

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
        allocated_port.__set_used_by(Port.ALLOCATED)
        db.session.commit()
        return allocated_port



def init_database(dbase, lowest_port, highest_port):
    for port_number in range(lowest_port, highest_port+1):
        available_port = Port(port_number)
        db.session.add(available_port)
    db.session.commit()