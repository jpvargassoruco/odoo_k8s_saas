# Aeisoftware Odoo Addons

Custom Odoo addons for the Aeisoftware K3s SaaS platform.

## Modules

### `odoo_k8s_saas`
Auto-provisions Odoo instances on K3s when a SaaS sale order is confirmed.
- Calls `portal.aeisoftware.com` API on `sale.order` confirm
- Sends branded "Your Odoo is ready" email to the customer
- Tracks all instances in SaaS → Instances menu

## Usage
Set as `addons_repo` when provisioning an instance via the portal.
The `initContainer` runs `git clone` / `git pull` on every pod start.
