#!/bin/bash
gunicorn -k flask_sockets.worker -t 5000  server:app
