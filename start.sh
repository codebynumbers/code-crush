#!/bin/bash
gunicorn -k flask_sockets.worker -t 5000 --bind 0.0.0.0:80 server:app
