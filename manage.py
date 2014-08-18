from flask import Flask
from flask.ext.script import Manager
import docker as Docker

app = Flask(__name__)
app.config.from_pyfile('application.cfg', silent=True)

manager = Manager(app)

@manager.command
def download_images():
    docker = Docker.Client(base_url='unix://var/run/docker.sock',
            version='1.9',
            timeout=5)

    for lang in app.config['IMAGES'].items():
        image_name = lang[1]['name']
        if not docker.images(name=image_name):
            print "Pulling image_name"
            print docker.pull(image_name)


if __name__ == "__main__":
    manager.run()


