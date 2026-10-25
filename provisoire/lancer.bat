@echo off
rem Lance le serveur CampusTwin en simulation et ouvre le jumeau dans le navigateur (il faut Python)
cd /d %~dp0
start "" http://localhost:8000/
python serveur\serveur.py --simulation --vitesse 120
