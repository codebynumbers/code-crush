#!/bin/bash
cd /home/ubuntu/code-crush
/home/ubuntu/code-crush/venv/bin/gunicorn -k flask_sockets.worker -t 5000 --bind 0.0.0.0:80 server:app
