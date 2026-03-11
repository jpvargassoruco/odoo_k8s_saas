# odoo_k8s_saas

Odoo 18 module — auto-provisions K3s Odoo instances on sale order confirm.

## Features
- `saas.instance` model with full lifecycle tracking
- `sale.order` hook: confirm → call portal API → provision instance
- Product template SaaS fields (version, DB template, addons repo, image)
- Branded "Your Odoo is ready 🚀" customer email
- SaaS menu in Odoo backend

## Installation
Copy to your Odoo addons path and install from Settings → Apps.

## Configuration
Settings → General Settings → SaaS Provisioning Portal:
- **Portal URL**: `https://portal.aeisoftware.com`
- **API Key**: your portal API key
