# -*- coding: utf-8 -*-

"""
Code Crush
===========
This simple application uses WebSockets to run a shared text editor.
Allows "safe" remote code execution via docker.
"""

import os
import redis
import gevent
import docker as Docker
import simplejson as json
import shutil
from flask import Flask, render_template
from flask_sockets import Sockets
from random import randint


app = Flask(__name__)
app.config.from_pyfile('application.cfg', silent=True)
app.logger.setLevel(app.config['LOGLEVEL'])

sockets = Sockets(app)
redis = redis.from_url(app.config['REDIS_URL'])

cwd = os.path.dirname(os.path.realpath(__file__))

# Re build client and image each time so we don't get all the old logs
docker = Docker.Client(base_url='unix://var/run/docker.sock',
            version='1.9',
            timeout=5)

images = {
    'Python': {
        'name': 'dockerfile/python',
        'run': '/usr/bin/python /mnt/code/run',
    },
    'PHP': {
        'name': 'darh/php-essentials',
        'run': '/usr/bin/php /mnt/code/run',
    },
    'Perl': {
        'name': 'dockerfile/python',
        'run': '/usr/bin/perl /mnt/code/run',
    },
    'Java': {
        'name': 'dockerfile/java',
        'run': '/bin/bash -c "cd /mnt/code && /usr/bin/javac run.java && /usr/bin/java Main"',
        'ext': '.java'
    },
    'Ruby': {
        'name': 'dockerfile/ruby',
        'run': '/usr/bin/ruby /mnt/code/run',
    },
    'JavaScript': {
        'name': 'dockerfile/nodejs',
        'run': '/usr/local/bin/node /mnt/code/run',
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
        self.pubsub.subscribe(app.config['REDIS_CHAN'])


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
        redis.publish(app.config['REDIS_CHAN'], message)


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

    # psuedo-unique-tempdir
    # TODO switch this to tempfile.mkdtemp
    rand = randint(1, 999999999)
    runpath = "%s/unsafe/%d" % (cwd, rand)
    runfile = "%s/run%s" % (runpath, images[lang].get('ext', '') )
    os.mkdir(runpath)

    with open(runfile, 'w') as outfile:
        outfile.write(message_dict['full_text'])

    container_id = docker.create_container(
        images[lang]['name'],
        command=images[lang]['run'],
        volumes=['/mnt/code'])

    res = docker.start(container_id,
        binds={runpath: '/mnt/code' })

    output = "\n".join([line for line in docker.logs(container_id, stream=True)])
    message_dict['results'] = output
    del message_dict['full_text']

    # Docker Cleanup
    try:
        docker.stop(container_id)
        docker.remove_container(container_id)
    except Exception as e:
        print e

    # Tempfile cleanup
    try:
        shutil.rmtree(runpath)
    except Exception as e:
        print e


if __name__ == "__main__":
    app.run()
