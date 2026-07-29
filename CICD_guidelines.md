# Charity Connect Backend CI/CD Guide

## Overview

The Charity Connect backend uses **GitHub Actions** to automatically deploy the latest code to the production server whenever changes are pushed to the `main` branch.

This removes the need to manually SSH into the server and deploy the application after every update.

---

# CI/CD Flow

```text
Developer
    │
    ▼
git push origin main
    │
    ▼
GitHub Repository
    │
    ▼
GitHub Actions
    │
    ▼
Connect to VPS via SSH
    │
    ▼
Pull Latest Code
    │
    ▼
Install Dependencies
    │
    ▼
Restart Backend Service
    │
    ▼
Verify Application Health
    │
    ▼
Deployment Completed
```

---

# Prerequisites

Before configuring CI/CD, ensure the following are already set up:

- Backend application deployed on the VPS.
- Git repository hosted on GitHub.
- Python virtual environment created.
- FastAPI running through **Uvicorn**.
- Backend managed by **systemd**.
- Nginx configured as a reverse proxy.
- Git installed on the VPS.

---

# Step 1: Generate SSH Keys

GitHub Actions requires secure access to the VPS.

Generate an SSH key pair:

```bash
ssh-keygen -t ed25519
```

This creates:

- `id_ed25519` (Private Key)
- `id_ed25519.pub` (Public Key)

### Add the Public Key to the VPS

Append the contents of `id_ed25519.pub` to:

```text
~/.ssh/authorized_keys
```

This authorises GitHub Actions to connect to the server.

---

# Step 2: Configure GitHub Secrets

Open:

**GitHub Repository → Settings → Secrets and Variables → Actions**

Create the following secrets.

| Secret | Description |
|---------|-------------|
| `HOST` | Public IP address of the VPS |
| `USERNAME` | SSH username (e.g. `root`) |
| `SSH_PRIVATE_KEY` | Contents of the private SSH key (`id_ed25519`) |

These secrets are securely accessed by GitHub Actions during deployment.

---

# Step 3: Create the Workflow

Create the following file inside the repository:

```text
.github/workflows/deploy.yml
```

Configure the workflow to run whenever code is pushed to the `main` branch.

```yaml
on:
  push:
    branches:
      - main
```

---

# Step 4: Deployment Process

The workflow performs the following actions.

## 1. Connect to the VPS

Uses the SSH credentials stored in GitHub Secrets to establish a secure connection.

---

## 2. Navigate to the Project Directory

```bash
cd /root/charity-connect-backend
```

Moves into the backend project directory.

---

## 3. Pull the Latest Source Code

```bash
git pull origin main
```

Downloads the latest commit from the GitHub repository.

---

## 4. Install or Update Dependencies

```bash
/root/charity-connect-backend/venv/bin/pip install -r requirements.txt
```

Installs any new Python packages required by the latest code.

---

## 5. Restart the Backend Service

```bash
systemctl restart charity.service
```

Restarts the FastAPI application so that the latest code is loaded.

---

## 6. Wait for the Application to Start

```bash
sleep 5
```

Provides sufficient time for the backend service to initialise.

---

## 7. Verify the Deployment

```bash
curl -f http://127.0.0.1:8000/health
```

Performs a health check to confirm the backend is running successfully.

---

# Workflow File

```yaml
name: Deploy Backend

on:
  push:
    branches:
      - main

jobs:
  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest

    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.2.2

        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USERNAME }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}

          script: |
            set -e

            cd /root/charity-connect-backend

            echo "Pulling latest code..."
            git pull origin main

            echo "Installing dependencies..."
            /root/charity-connect-backend/venv/bin/pip install -r requirements.txt

            echo "Restarting backend..."
            systemctl restart charity.service

            echo "Waiting for service..."
            sleep 5

            echo "Performing health check..."
            curl -f http://127.0.0.1:8000/health

            echo "Deployment completed successfully!"
```

---

# How to Deploy

Once the workflow is configured, deployment becomes automatic.

Simply commit and push your changes:

```bash
git add .
git commit -m "Describe your changes"
git push origin main
```

GitHub Actions will automatically:

1. Detect the new commit.
2. Connect to the VPS.
3. Pull the latest source code.
4. Install any new dependencies.
5. Restart the backend service.
6. Verify the application is running.
7. Mark the deployment as successful.

No manual SSH login or deployment steps are required.

---

# Benefits

- Automatic deployment after every push to the `main` branch.
- Secure server authentication using SSH keys.
- Consistent deployment process across all updates.
- Automatic dependency installation.
- Automatic backend restart.
- Built-in health check after deployment.
- Centralised deployment logs available in GitHub Actions.
- Faster and more reliable release process.