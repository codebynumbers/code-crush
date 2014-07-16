# -*- coding: utf-8 -*-

"""
Code Crush
===========
This simple application uses WebSockets to run a shared text editor.
Allows "safe" remote code execution via docker.
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
        'name': 'dockerfile/python',
        'run': '/usr/bin/python /mnt/code/{runfile}',
        'ext': 'py'
    },
    'PHP': {
        'name': 'darh/php-essentials',
        'run': '/usr/bin/php /mnt/code/{runfile}',
        'ext': 'php'
    },
    'Perl': {
        'name': 'dockerfile/python',
        'run': '/usr/bin/perl /mnt/code/{runfile}',
        'ext': 'pl'
    },
    'Java': {
        'name': 'dockerfile/java',
        'run': '/bin/bash -c "cd /mnt/code && /usr/bin/javac /mnt/code/{runfile} && /usr/bin/java Main"',
        'ext': 'java'
    },
    'Ruby': {
        'name': 'dockerfile/ruby',
        'run': '/usr/bin/ruby /mnt/code/{runfile}',
        'ext': 'rb'
    },
    'JavaScript': {
        'name': 'dockerfile/nodejs',
        'run': '/usr/local/bin/node /mnt/code/{runfile}',
        'ext': 'js'
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
        # Sleep to prevent *constant* context-switches.
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
        command=images[lang]['run'].format(runfile=runfile),
        volumes=['/mnt/code'])

    res = docker.start(container_id,
        binds={'%s/unsafe' % cwd: '/mnt/code' })

    output = "\n".join([line for line in docker.logs(container_id, stream=True)])
    message_dict['results'] = output
    del message_dict['full_text']

    # Cleanup
    try:
        os.unlink(runpath)
        docker.stop(container_id)
        docker.remove_container(container_id)
    except Exception as e:
        print e


if __name__ == "__main__":
    app.run()
