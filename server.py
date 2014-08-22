# -*- coding: utf-8 -*-

"""
Code Crush
===========
This simple application uses WebSockets to run a shared text editor.
Allows "safe" remote code execution via docker.
"""

import os
import redis
import docker as Docker
import simplejson as json
import shutil
import gevent
from flask import Flask, render_template
from flask_sockets import Sockets
from random import randint
from backend import Backend


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

editors = Backend(redis, app.config['REDIS_CHAN'])
editors.start()


@app.route('/', defaults={'room':'default'})
@app.route('/<room>')
def index(room):
    return render_template('index.html', room=room)

@sockets.route('/ws/submit/<room>')
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


@sockets.route('/ws/receive/<room>')
def outbox(ws, room):
    """Sends outgoing messages, via `Backend`."""
    editors.register(ws, room)

    while ws.socket is not None:
        # Context switch while `Backend.start` is running in the background.
        gevent.sleep()


def run_code(message_dict):
    lang = message_dict['language']
    if lang not in app.config['IMAGES']:
        app.logger.debug(u'Unsupported language')
        return

    # psuedo-unique-tempdir
    # TODO switch this to tempfile.mkdtemp
    rand = randint(1, 999999999)
    runpath = "%s/unsafe/%d" % (cwd, rand)
    runfile = "%s/run%s" % (runpath, app.config['IMAGES'][lang].get('ext', '') )
    os.mkdir(runpath)

    with open(runfile, 'w') as outfile:
        outfile.write(message_dict['full_text'])

    container_id = docker.create_container(
        app.config['IMAGES'][lang]['name'],
        command=app.config['IMAGES'][lang]['run'],
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
    app.run(host='0.0.0.0')
