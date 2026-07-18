#!/bin/bash
cd /var/www/claudez
exec python3 main.py --web --host 0.0.0.0 --port 8080
