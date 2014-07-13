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
from random import randint

REDIS_URL = 'redis://localhost:6379' #os.environ['REDISCLOUD_URL']
REDIS_CHAN = 'editor'

app = Flask(__name__)
app.debug = True #'DEBUG' in os.environ
app.logger.setLevel(logging.DEBUG)

sockets = Sockets(app)
redis = redis.from_url(REDIS_URL)

cwd = os.path.dirname(os.path.realpath(__file__))

# Re build client and image each time so we don't get all the old logs
docker = Docker.Client(base_url='unix://var/run/docker.sock',
            version='1.9',
            timeout=5)

images = {
    'Python': {
        'name': 'exekias/python',
        'run': '/usr/bin/python',
        'ext': 'php'
    },
    'PHP': {
        'name': 'darh/php-essentials',
        'run': '/usr/bin/php',
        'ext': 'php'
    }
}

class Backend(object):
    """Interface for registering and updating WebSocket clients."""

    def __init__(self):
        # map of room => clients[]
        self.room_clients = {}
        # map of clients => room
        self.client_room = {}        

        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(REDIS_CHAN)


    def __iter_data(self):
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message':
                #app.logger.info(u'Sending message: {}'.format(data))
                yield data

    def register(self, client, room):
        """Register a WebSocket connection for Redis updates."""
        if not self.room_clients.get(room):
            self.room_clients[room] = []
        self.room_clients[room].append(client)
        self.client_room[client] = room

    def send(self, client, data):
        """Send given data to the registered client.
        Automatically discards invalid connections."""
        try:
            client.send(data)
        except Exception:
            # find client's room and remove them from appropriate list
            room = self.client_room[client]
            self.room_clients[room].remove(client)

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for data in self.__iter_data():
            room = json.loads(data)['room']
            for client in self.room_clients.get(room, []):
                gevent.spawn(self.send, client, data)

    def start(self):
        """Maintains Redis subscription in the background."""
        gevent.spawn(self.run)

editors = Backend()
editors.start()


@app.route('/', defaults={'room':'default'})
@app.route('/<room>')
def index(room):
    return render_template('index.html', room=room)

@sockets.route('/submit/<room>')
def inbox(ws, room):
    """Receives incoming messages, inserts them into Redis."""
    while ws.socket is not None:
        # Sleep to prevent *contstant* context-switches.
        gevent.sleep(0.1)
        message = ws.receive()
        if not message:
            continue
        
        message_dict = json.loads(message)
        message_dict['room'] = room

        if message_dict.get('type') == 'run':
            run_code(message_dict)

        message = json.dumps(message_dict)
        #app.logger.info(u'Inserting message: {}'.format(message))
        redis.publish(REDIS_CHAN, message)


@sockets.route('/receive/<room>')
def outbox(ws, room):
    """Sends outgoing messages, via `Backend`."""
    editors.register(ws, room)

    while ws.socket is not None:
        # Context switch while `Backend.start` is running in the background.
        gevent.sleep()



def run_code(message_dict):
    lang = message_dict['language']
    if lang not in images:
        app.logger.debug(u'Unsupported language')
        return

    # psuedo-unique-tempfile
    runfile = 'run_%d.%s' % (randint(1, 999999999), images[lang]['ext'])
    runpath = "%s/unsafe/%s" % (cwd, runfile)

    with open(runpath, 'w') as outfile:
        outfile.write(message_dict['full_text'])

    container_id = docker.create_container(
        images[lang]['name'], 
        command="%s /mnt/code/%s > /mnt/code/output.txt" % (images[lang]['run'], runfile), 
        volumes=['/mnt/code'])

    docker.start(container_id, 
        binds={'%s/unsafe' % cwd: '/mnt/code' })

    # Give container a chance to run code
    output = None
    for i in range(10):
        output = docker.logs(container_id)         
        if output:
            app.logger.debug("logs for %s %s" % (images[lang]['run'], runfile))
            app.logger.debug(output)
            break
        else:
            gevent.sleep(0.5)

    message_dict['results'] = output
    del message_dict['full_text']

    # Cleanup
    os.unlink(runpath)
    docker.stop(container_id)
    docker.remove_container(container_id)

    return None
