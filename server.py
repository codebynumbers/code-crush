# -*- coding: utf-8 -*-

"""
Server
===========

This simple application uses WebSockets to run a shared text editor.
Remote code execution via docker coming soon.
"""

import os
import logging
import redis
import gevent
import docker as Docker
import simplejson as json
from flask import Flask, render_template
from flask_sockets import Sockets

REDIS_URL = 'redis://localhost:6379' #os.environ['REDISCLOUD_URL']
REDIS_CHAN = 'editor'

app = Flask(__name__)
app.debug = 'DEBUG' in os.environ

sockets = Sockets(app)
redis = redis.from_url(REDIS_URL)

cwd = os.path.dirname(os.path.realpath(__file__))

# Re build client and image each time so we don't get all the old logs
docker = Docker.Client(base_url='unix://var/run/docker.sock',
            version='1.9',
            timeout=5)

class Backend(object):
    """Interface for registering and updating WebSocket clients."""

    def __init__(self):
        self.clients = list()
        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(REDIS_CHAN)


    def __iter_data(self):
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message':
                app.logger.info(u'Sending message: {}'.format(data))
                yield data

    def register(self, client):
        """Register a WebSocket connection for Redis updates."""
        self.clients.append(client)

    def send(self, client, data):
        """Send given data to the registered client.
        Automatically discards invalid connections."""
        try:
            client.send(data)
        except Exception:
            self.clients.remove(client)

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for data in self.__iter_data():
            for client in self.clients:
                gevent.spawn(self.send, client, data)

    def start(self):
        """Maintains Redis subscription in the background."""
        gevent.spawn(self.run)

editors = Backend()
editors.start()


@app.route('/')
def index():
    return render_template('index.html')

@sockets.route('/submit')
def inbox(ws):
    """Receives incoming messages, inserts them into Redis."""
    while ws.socket is not None:
        # Sleep to prevent *contstant* context-switches.
        gevent.sleep(0.1)
        message = ws.receive()
        if not message:
            continue
        
        message_dict = json.loads(message)
        if message_dict.get('type') == 'run':

            with open('%s/unsafe/run.py' % cwd, 'w') as outfile:
                outfile.write(message_dict['full_text'])

            container_id = docker.create_container('exekias/python', command='/usr/bin/python /mnt/code/run.py', volumes=['/mnt/code'])
            docker.start(container_id, 
                binds={'%s/unsafe' % cwd: '/mnt/code' })

            # Give container a chance to run code
            gevent.sleep(0.1)            

            message_dict['results'] = docker.logs(container_id)
            del message_dict['full_text']
            message = json.dumps(message_dict)

            # Cleanup
            docker.stop(container_id)
            docker.remove_container(container_id)

        app.logger.info(u'Inserting message: {}'.format(message))
        redis.publish(REDIS_CHAN, message)


@sockets.route('/receive')
def outbox(ws):
    """Sends outgoing messages, via `Backend`."""
    editors.register(ws)

    while ws.socket is not None:
        # Context switch while `Backend.start` is running in the background.
        gevent.sleep()

