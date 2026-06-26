# Immobilier Poller

Background worker Python hébergé sur **Render**. Surveille une boîte Gmail via IMAP et forwarde les emails d'Immoweb/Immovlan vers le pipeline de traitement IA.

## Fonctionnement

```
Gmail (IMAP)
  └── poll toutes les 60s
       └── email de noreply@immoweb.be ou immovlan.be ?
            └── POST /api/process-email  ← Next.js sur Vercel
```

## Variables d'environnement

| Variable | Description |
|----------|-------------|
| `GMAIL_ADDRESS` | Adresse Gmail surveillée |
| `GMAIL_APP_PASSWORD` | App password Gmail (16 caractères) |
| `PIPELINE_URL` | URL de la route Next.js : `https://ton-app.vercel.app/api/process-email` |
| `PROCESS_EMAIL_SECRET` | Secret partagé avec l'API Next.js (header `x-pipeline-secret`) |
| `ALLOWED_SENDERS` | Expéditeurs autorisés, séparés par virgule |
| `POLL_INTERVAL_SECONDS` | Intervalle de polling (défaut : 60) |

## Setup Gmail

1. [myaccount.google.com](https://myaccount.google.com) → Sécurité → Validation en deux étapes → Activer
2. Sécurité → Mots de passe des applications → Créer → copier les 16 caractères
3. Gmail → Paramètres → Transfert et POP/IMAP → Activer IMAP

## Déploiement sur Render

1. New → Background Worker → connecter ce repo
2. Root directory : `.`
3. Render détecte `render.yaml` automatiquement
4. Ajouter les variables d'environnement dans le dashboard Render

## Test local

```bash
pip install -r requirements.txt
cp .env.example .env   # remplir les vraies valeurs
python worker.py
```
