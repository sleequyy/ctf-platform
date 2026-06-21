# Plateforme de Challenges CTF - BTS SIO

Plateforme de defis techniques (CTF) pour etudiants BTS SIO.
Chaque challenge est un environnement Docker temporaire lance a la demande via une API.

## Architecture

- **Serveur API (Flask)** : gere le lancement/arret des containers de challenges
- **Challenges Docker** : 3 mini-challenges Linux (Foret, Labyrinthe, MonProfil)
- **Acces** : SSH avec l'utilisateur `candidat` (droits limites)

## Technologies

- Python 3.10 + Flask
- Docker / Docker Compose
- SDK Docker Python

## Besoins couverts

1. Gestion des ports et containers (ouverture/fermeture/destruction)
2. Securite : whitelist des images autorisees
3. Logs : succes / erreurs
4. Personnalisation via ports.json
5. Code different a chaque lancement (variable CHALLENGE_CODE)

## Lancement

\`\`\`bash
docker-compose up -d
\`\`\`

## API - Endpoints

| Methode | Endpoint | Description |
|---------|----------|-------------|
| GET | /api/health | Verifier l'etat de l'API |
| GET | /api/challenges | Lister les challenges |
| POST | /api/challenge/<nom>/start | Lancer un challenge |
| POST | /api/challenge/<nom>/stop | Arreter un challenge |
| GET | /api/logs | Consulter les logs |
| POST | /api/cleanup | Nettoyer tous les containers |

## Exemple d'utilisation

\`\`\`bash
# Lancer un challenge
curl -X POST http://IP:8000/api/challenge/foret/start

# Se connecter
ssh -p 2221 candidat@IP

# Arreter
curl -X POST http://IP:8000/api/challenge/foret/stop \
  -H "Content-Type: application/json" \
  -d '{"container_name":"foret-xxxx","port":2221}'
\`\`\`

## Structure du projet

\`\`\`
ctf-platform/
├── api/
│   ├── app.py            # API Flask
│   ├── requirements.txt
│   ├── Dockerfile
│   └── ports.json        # Gestion des ports
├── ssh-build/            # Dockerfiles des challenges (ajout SSH)
├── docker-compose.yml
└── README.md
\`\`\`

## Architecture distribuee (mise a jour)

L'API a ete deplacee sur un serveur dedie (Serveur B, 192.168.0.17),
non dockerisee, qui pilote le Docker du Serveur A (192.168.0.16) via SSH.

- Serveur A (192.168.0.16) : Docker + containers des challenges
- Serveur B (192.168.0.17) : API Flask (Python natif)

Code de la nouvelle API : voir dossier `api-distante/`

### Nouveautes
- Pool de 5000 ports (3000-7999)
- Auto-destruction des containers apres 3h
- Personnalisation : port interne, cle de securite, RAM, CPU
- Monitoring : GET /api/active
