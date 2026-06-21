from flask import Flask, jsonify, request
from datetime import datetime
import docker, json, uuid, logging, os, threading, time

app = Flask(__name__)

DOCKER_HOST  = "ssh://debian@192.168.0.16"
HOST_IP      = "192.168.0.16"
TIMEOUT_MIN  = 180       # 3 heures
PORT_MIN     = 3000
PORT_MAX     = 7999      # 5000 ports (3000-7999)

client = docker.DockerClient(base_url=DOCKER_HOST)

ALLOWED_IMAGES = {
    "foret":      "sleequy999/challenge-foret:ssh",
    "labyrinthe": "sleequy999/challenge-labyrinthe:ssh",
    "monprofil":  "sleequy999/challenge-monprofil:ssh",
}

INTERNAL_PORTS = {
    "foret":      22,
    "labyrinthe": 22,
    "monprofil":  22,
}

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PORTS_FILE = os.path.join(BASE_DIR, "ports.json")
LOG_DIR    = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(filename=os.path.join(LOG_DIR, "app.log"),
                    level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ===== Helpers ports (pool global) =====
def load_ports():
    with open(PORTS_FILE) as f:
        return json.load(f)

def save_ports(d):
    with open(PORTS_FILE, "w") as f:
        json.dump(d, f)

def get_port(challenge, cname):
    d = load_ports()
    if not d["available"]:
        return None
    port = d["available"].pop(0)
    d["in_use"][str(port)] = {
        "challenge":      challenge,
        "container_name": cname,
        "started_at":     datetime.utcnow().isoformat()
    }
    save_ports(d)
    return port

def free_port(port):
    d = load_ports()
    p = str(port)
    if p in d["in_use"]:
        del d["in_use"][p]
    port = int(port)
    if port not in d["available"]:
        d["available"].append(port)
    save_ports(d)

def age_min(started_at):
    dt = datetime.strptime(started_at[:19], "%Y-%m-%dT%H:%M:%S")
    return (datetime.utcnow() - dt).total_seconds() / 60

def find_port_by_container(cname):
    d = load_ports()
    for p, info in d["in_use"].items():
        if info.get("container_name") == cname:
            return int(p)
    return None

# ===== Routes =====
@app.route("/")
def home():
    return jsonify({
        "service": "CTF Platform API",
        "endpoints": {
            "GET  /api/health":                   "etat de l'API",
            "GET  /api/challenges":               "stats des ports",
            "GET  /api/active":                   "sessions en cours",
            "POST /api/challenge/<nom>/start":    "lancer un challenge",
            "POST /api/challenge/<nom>/stop":     "arreter un challenge",
            "GET  /api/logs":                     "journaux",
            "POST /api/cleanup":                  "tout nettoyer",
        }
    }), 200

@app.route("/api/health")
def health():
    return jsonify({
        "status":      "ok",
        "docker_ping": client.ping(),
        "timestamp":   datetime.now().isoformat()
    }), 200

@app.route("/api/challenges")
def challenges():
    d = load_ports()
    return jsonify({
        "challenges":        list(ALLOWED_IMAGES.keys()),
        "total_ports":       PORT_MAX - PORT_MIN + 1,
        "available_ports":   len(d["available"]),
        "in_use_ports":      len(d["in_use"]),
        "timeout_minutes":   TIMEOUT_MIN,
        "timeout_heures":    TIMEOUT_MIN // 60
    }), 200

@app.route("/api/active")
def active():
    d = load_ports()
    out = []
    for p, info in d["in_use"].items():
        age  = round(age_min(info.get("started_at", datetime.utcnow().isoformat())), 1)
        out.append({
            "port":           int(p),
            "challenge":      info.get("challenge"),
            "container_name": info.get("container_name"),
            "started_at":     info.get("started_at"),
            "age_min":        age,
            "expires_in_min": round(TIMEOUT_MIN - age, 1)
        })
    return jsonify({
        "active":           out,
        "count":            len(out),
        "available_ports":  len(d["available"])
    }), 200

@app.route("/api/challenge/<name>/start", methods=["POST"])
def start(name):
    if name not in ALLOWED_IMAGES:
        logging.warning(f"START REFUSED - {name}")
        return jsonify({"error": "Challenge non autorise"}), 403

    # ===== PERSONNALISATION (besoin 4) =====
    params = request.get_json(silent=True, force=True) or {}
    internal_port = params.get("internal_port", INTERNAL_PORTS.get(name, 22))
    security_key  = params.get("security_key", None)
    memory        = params.get("memory", "512m")
    cpu           = params.get("cpu", "1.0")
    extra_env     = params.get("env", {})

    code  = str(uuid.uuid4())[:8]
    cname = f"{name}-{code}"
    port  = get_port(name, cname)

    if not port:
        logging.error(f"START FAILED - no port - {name}")
        return jsonify({"error": "Aucun port disponible"}), 503

    # Variables d'environnement du container
    env = {
        "CHALLENGE_CODE": code,
        **extra_env
    }
    if security_key:
        env["SECURITY_KEY"] = security_key

    try:
        client.containers.run(
            ALLOWED_IMAGES[name],
            name=cname,
            ports={f"{internal_port}/tcp": port},
            detach=True,
            environment=env,
            mem_limit=memory,
            nano_cpus=int(float(cpu) * 1e9)
        )
        logging.info(f"START OK - {name} port={port} internal={internal_port} container={cname}")
        return jsonify({
            "protocol":       "ssh",
            "ip":             HOST_IP,
            "port":           port,
            "internal_port":  internal_port,
            "username":       "candidat",
            "password":       "password123",
            "container_name": cname,
            "challenge":      name,
            "expires_in_min": TIMEOUT_MIN,
            "options": {
                "memory":       memory,
                "cpu":          cpu,
                "security_key": security_key,
                "extra_env":    extra_env
            }
        }), 201
    except Exception as e:
        free_port(port)
        logging.error(f"START ERROR - {name}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/challenge/<name>/stop", methods=["POST"])
def stop(name):
    data  = request.get_json() or {}
    cname = data.get("container_name")
    if not cname:
        return jsonify({"error": "container_name requis"}), 400

    port = find_port_by_container(cname)

    try:
        c = client.containers.get(cname)
        c.stop(timeout=5)
        c.remove()
        logging.info(f"STOP OK - {cname} port={port}")
    except docker.errors.NotFound:
        logging.warning(f"STOP - container not found: {cname}")
    except Exception as e:
        logging.error(f"STOP ERROR - {cname}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if port:
            free_port(port)

    return jsonify({"status": "stopped", "port_freed": port}), 200

@app.route("/api/logs")
def logs():
    try:
        with open(os.path.join(LOG_DIR, "app.log")) as f:
            return jsonify({"logs": f.readlines()[-50:]}), 200
    except Exception:
        return jsonify({"logs": []}), 200

@app.route("/api/cleanup", methods=["POST"])
def cleanup():
    d = load_ports()
    n = 0
    for p, info in list(d["in_use"].items()):
        cname = info.get("container_name")
        try:
            c = client.containers.get(cname)
            c.stop(timeout=5)
            c.remove()
            n += 1
        except Exception:
            pass
    d["available"] = list(range(PORT_MIN, PORT_MAX + 1))
    d["in_use"]    = {}
    save_ports(d)
    logging.info(f"CLEANUP - {n} containers removed, ports reset")
    return jsonify({"removed": n, "ports_reset": PORT_MAX - PORT_MIN + 1}), 200

# ===== Auto-destruction apres 3h =====
def auto_cleanup():
    while True:
        time.sleep(300)  # toutes les 5 min
        try:
            d = load_ports()
            expired = [(int(p), info) for p, info in d["in_use"].items()
                       if age_min(info.get("started_at", datetime.utcnow().isoformat())) > TIMEOUT_MIN]
            for port, info in expired:
                cname = info.get("container_name")
                try:
                    c = client.containers.get(cname)
                    c.stop(timeout=5)
                    c.remove()
                except Exception:
                    pass
                free_port(port)
                logging.info(f"AUTO-DESTROY - {cname} port={port} (3h ecoulees)")
        except Exception as e:
            logging.error(f"AUTO-CLEANUP ERROR: {e}")

if __name__ == "__main__":
    threading.Thread(target=auto_cleanup, daemon=True).start()
    logging.info("API started - 5000 ports (3000-7999) - timeout 3h")
    app.run(host="0.0.0.0", port=8000)
