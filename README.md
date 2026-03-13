# odoo_k8s_saas — K8s SaaS Provisioning for Odoo

Odoo module that **auto-provisions Odoo instances on a K3s cluster** when a sale order is confirmed.  
It connects to the [Aeisoftware SaaS Portal](https://portal.aeisoftware.com) REST API to create, manage, and delete instances.

## How It Works

```
Customer buys a "SaaS Plan" product on Odoo E-commerce
         │
         ▼
  Sale Order confirmed → action_confirm()
         │
         ▼
  Module calls POST /api/instances on the SaaS Portal
         │
         ▼
  Portal provisions: Namespace → PVCs → Deployment → Service → Ingress → Cloudflare DNS
         │
         ▼
  Customer receives "Instance Ready 🚀" email with their URL
```

## Features

| Feature | Description |
|:---|:---|
| **Auto-provisioning** | Confirming a sale order with a SaaS product triggers instance creation |
| **Instance management** | View, provision, cancel, and delete instances from within Odoo |
| **Product configuration** | SaaS Plan tab on products: Odoo version, DB template, addons repo, workers, domain suffix |
| **Settings** | Portal URL and API Key configurable under *Settings → SaaS Provisioning Portal* |
| **Email notification** | Branded email sent to the customer when the instance is ready |
| **Chatter integration** | All provisioning events logged to the instance's mail thread |
| **Smart buttons** | Sale order shows instance count with quick navigation |

## Models

| Model | Type | Description |
|:---|:---|:---|
| `saas.instance` | New | Tracks provisioned instances (name, domain, version, state, customer) |
| `product.template` | Extended | Adds SaaS Plan fields (version, template, addons repo, image, workers, domain suffix) |
| `sale.order` | Extended | On confirm, auto-creates `saas.instance` for each SaaS Plan line |
| `sale.order.line` | Extended | Links to the created `saas.instance` |
| `res.config.settings` | Extended | Portal URL and API Key settings |

## Installation

### Prerequisites

- Odoo 18 (or 19) with modules: `base`, `sale`, `mail`, `portal`
- Access to the [SaaS Portal API](https://portal.aeisoftware.com)
- A valid Portal API key

### Steps

1. **Clone this repo** into your Odoo addons directory:
   ```bash
   git clone https://github.com/jpvargassoruco/odoo_k8s_saas.git /mnt/extra-addons/odoo_k8s_saas
   ```

2. **Add to `addons_path`** in `odoo.conf`:
   ```ini
   addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
   ```
   > The `/mnt/extra-addons` entry is enough — Odoo scans subdirectories for `__manifest__.py`.

3. **Restart Odoo** and go to *Apps → Update Apps List*.

4. **Search** for "K8s SaaS Provisioning" and click **Activate**.

5. **Configure** the portal connection:
   - Go to *Settings → SaaS Provisioning Portal*
   - Set the **Portal URL** (e.g. `https://portal.aeisoftware.com`)
   - Set the **API Key**

## Usage

### Create a SaaS Product

1. Go to *Sales → Products* → Create a new product
2. Toggle **Is SaaS Plan** on
3. Fill in the **SaaS Plan** tab:
   - **Odoo Version**: 17, 18, or 19
   - **Workers**: number of Odoo workers (default: 2)
   - **Domain Suffix**: e.g. `.aeisoftware.com`
   - **DB Template** (optional): path in Ceph RGW, e.g. `v18/starter.dump`
   - **Addons Git Repo** (optional): URL to a git repo with custom addons
   - **Custom Docker Image** (optional): e.g. `ghcr.io/org/odoo-custom:18`

### Provision an Instance

1. Create a **Sale Order** with the SaaS product
2. **Confirm** the order → the module automatically:
   - Creates a `saas.instance` record
   - Calls `POST /api/instances` on the portal
   - Sends a "ready" email to the customer

### Manage Instances

- Navigate to *SaaS → Instances* to view all instances
- Click an instance to see details, provision, cancel, or open it
- The sale order shows an **Instances** smart button linking to its instances

## File Structure

```
odoo_k8s_saas/
├── __init__.py
├── __manifest__.py
├── README.md
├── data/
│   └── mail_template.xml          # "Instance Ready 🚀" email template
├── models/
│   ├── __init__.py
│   ├── saas_instance.py           # saas.instance model + portal API calls
│   ├── sale_order.py              # Extended sale.order + product.template
│   └── res_config_settings.py     # Portal URL & API Key settings
├── security/
│   └── ir.model.access.csv        # ACL: admin full, user read-only
├── views/
│   ├── saas_instance_views.xml    # Form + list + menu for saas.instance
│   ├── sale_order_views.xml       # Smart button on sale.order
│   ├── product_template_views.xml # SaaS Plan tab on product form
│   └── res_config_settings_views.xml  # Settings page section
└── wizards/                       # Reserved for future wizards
```

## Security

| Group | Read | Write | Create | Delete |
|:---|:---:|:---:|:---:|:---:|
| System (admin) | ✅ | ✅ | ✅ | ✅ |
| Internal User | ✅ | ❌ | ❌ | ❌ |

## Portal API Reference

The module communicates with the SaaS Portal via these endpoints:

| Action | Method | Endpoint |
|:---|:---|:---|
| Provision | `POST` | `/api/instances` |
| Delete | `DELETE` | `/api/instances/{name}?domain={domain}` |

Full API documentation: [Portal API Reference](https://github.com/jpvargassoruco/aeisoftware/wiki/Portal-API-Reference)

## License

LGPL-3 — see [LICENSE](https://www.gnu.org/licenses/lgpl-3.0.html)

## Author

[Aeisoftware](https://aeisoftware.com) — Built for the K3s SaaS Platform.
