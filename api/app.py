from flask import Flask, jsonify, request
import docker
import json
import uuid
import logging
import os
from datetime import datetime

app = Flask(__name__)
client = docker.from_env()

PORTS_FILE = "/app/ports.json"
LOG_DIR = "/app/logs"
HOST_IP = "192.168.0.16"

# SÉCURITÉ : seules ces images peuvent être lancées
ALLOWED_IMAGES = {
    "foret": "sleequy999/challenge-foret:ssh",
    "labyrinthe": "sleequy999/challenge-labyrinthe:ssh",
    "monprofil": "sleequy999/challenge-monprofil:ssh"
}

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=f"{LOG_DIR}/app.log",
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_ports():
    with open(PORTS_FILE, 'r') as f:
        return json.load(f)

def save_ports(data):
    with open(PORTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_available_port(name):
    data = load_ports()
    for c in data['challenges']:
        if c['name'] == name and c['available']:
            port = c['available'].pop(0)
            c['in_use'].append(port)
            save_ports(data)
            return port
    return None

def free_port(name, port):
    data = load_ports()
    for c in data['challenges']:
        if c['name'] == name and port in c['in_use']:
            c['in_use'].remove(port)
            c['available'].append(port)
            save_ports(data)
    return True

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

@app.route('/api/challenges', methods=['GET'])
def list_challenges():
    return jsonify(load_ports()['challenges']), 200

@app.route('/api/challenge/<name>/start', methods=['POST'])
def start(name):
    # SÉCURITÉ : refuser les images non autorisées
    if name not in ALLOWED_IMAGES:
        logging.warning(f"START REFUSED - unknown: {name}")
        return jsonify({"error": "Challenge non autorise"}), 403

    port = get_available_port(name)
    if not port:
        logging.error(f"START FAILED - no port: {name}")
        return jsonify({"error": "Aucun port disponible"}), 503

    code = str(uuid.uuid4())[:8]
    container_name = f"{name}-{code}"

    try:
        container = client.containers.run(
            ALLOWED_IMAGES[name],
            name=container_name,
            ports={'22/tcp': port},
            detach=True,
            environment={'CHALLENGE_CODE': code}
        )
        logging.info(f"START SUCCESS - {name} port={port} container={container_name} code={code}")
        return jsonify({
            "protocol": "ssh",
            "ip": HOST_IP,
            "port": port,
            "username": "candidat",
            "password": "password123",
            "container_name": container_name,
            "challenge": name
        }), 201
    except Exception as e:
        free_port(name, port)
        logging.error(f"START ERROR - {name}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/challenge/<name>/stop', methods=['POST'])
def stop(name):
    data = request.get_json() or {}
    container_name = data.get('container_name')
    port = data.get('port')

    if not container_name:
        return jsonify({"error": "container_name requis"}), 400

    try:
        container = client.containers.get(container_name)
        container.stop(timeout=5)
        container.remove()
        if port:
            free_port(name, port)
        logging.info(f"STOP SUCCESS - {container_name}")
        return jsonify({"status": "stopped"}), 200
    except docker.errors.NotFound:
        logging.error(f"STOP ERROR - not found: {container_name}")
        return jsonify({"error": "Container introuvable"}), 404
    except Exception as e:
        logging.error(f"STOP ERROR - {container_name}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def logs():
    try:
        with open(f"{LOG_DIR}/app.log") as f:
            return jsonify({"logs": f.readlines()[-50:]}), 200
    except:
        return jsonify({"logs": []}), 200

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    count = 0
    for c in client.containers.list(all=True):
        for name in ALLOWED_IMAGES:
            if c.name.startswith(f"{name}-"):
                try:
                    c.stop(timeout=5)
                    c.remove()
                    count += 1
                except:
                    pass
    data = load_ports()
    for c in data['challenges']:
        c['available'] = c['ports'].copy()
        c['in_use'] = []
    save_ports(data)
    logging.info(f"CLEANUP - {count} containers")
    return jsonify({"removed": count}), 200

if __name__ == '__main__':
    logging.info("API started")
    app.run(host='0.0.0.0', port=8000)
