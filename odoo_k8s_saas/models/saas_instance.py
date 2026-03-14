from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaasInstance(models.Model):
    _name = 'saas.instance'
    _description = 'SaaS Odoo Instance'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Instance Name', required=True, tracking=True)
    domain = fields.Char('Domain', required=True, tracking=True)
    url = fields.Char('URL', compute='_compute_url', store=True)
    odoo_version = fields.Selection(
        [('17', 'Odoo 17'), ('18', 'Odoo 18'), ('19', 'Odoo 19')],
        string='Odoo Version', required=True, default='18',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('provisioning', 'Provisioning'),
        ('running', 'Running'),
        ('error', 'Error'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)

    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', ondelete='set null')
    product_id = fields.Many2one('product.product', string='Plan')

    db_template = fields.Char('DB Template', help='e.g. v18/starter.zip — path in Ceph RGW S3')
    addons_repos = fields.Text(
        'Addons Repos (JSON)',
        help='JSON list: [{"url":"...","branch":"17.0"}]',
        default='[]',
    )
    custom_image = fields.Char('Custom Image', help='e.g. ghcr.io/org/odoo-custom:18')
    db_password = fields.Char('DB Password', default='odoo', groups='base.group_system')

    workers = fields.Integer('Workers', default=2)
    admin_passwd = fields.Char('Admin Password', required=True, groups='base.group_system')
    admin_email = fields.Char('Admin Email', required=True)
    admin_password = fields.Char('Admin Password (Initial)', required=True, groups='base.group_system')
    lang = fields.Selection(
        [('en_US', 'English'), ('es_ES', 'Spanish'), ('fr_FR', 'French'),
         ('de_DE', 'German'), ('pt_BR', 'Portuguese (BR)')],
        string='Language', default='en_US',
    )

    portal_response = fields.Text('Last Portal Response', readonly=True)
    error_message = fields.Text('Error', readonly=True)

    @api.depends('domain')
    def _compute_url(self):
        for rec in self:
            rec.url = f"https://{rec.domain}" if rec.domain else ''

    def action_open_instance(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self.url, 'target': 'new'}

    def action_provision(self):
        """Mark as provisioning and dispatch via ir.cron (non-blocking).

        OPTIMIZATION: The original used blocking requests.post() which tied up
        an Odoo worker for up to 30s. Now we just write the state and let
        ir.cron handle the actual API call in the background.
        """
        self.ensure_one()
        self.write({'state': 'provisioning', 'error_message': False})
        self.message_post(body="⏳ Provisioning queued — will be dispatched shortly.")
        # Trigger the cron immediately (instead of waiting for next interval)
        cron = self.env.ref('odoo_k8s_saas.cron_provision_instances', raise_if_not_found=False)
        if cron:
            cron.sudo().method_direct_trigger()

    def action_cancel(self):
        self.ensure_one()
        self._deprovision_via_portal()
        self.state = 'cancelled'

    def _get_portal_config(self):
        """Return (portal_url, api_key) from ir.config_parameter."""
        get = self.env['ir.config_parameter'].sudo().get_param
        portal_url = get('saas.portal_url', 'https://portal.aeisoftware.com')
        api_key = get('saas.api_key', '')
        return portal_url, api_key

    @api.model
    def _cron_provision_pending(self):
        """Cron job: provision all instances in 'provisioning' state that haven't been sent yet.

        OPTIMIZATION: Runs in background worker, doesn't block UI or sale order confirmation.
        """
        pending = self.search([('state', '=', 'provisioning'), ('portal_response', '=', False)])
        for instance in pending:
            try:
                instance._provision_via_portal()
            except Exception as e:
                _logger.error("Failed to provision %s: %s", instance.name, e)
                instance.write({'state': 'error', 'error_message': str(e)})

    @api.model
    def _cron_check_provisioning_status(self):
        """Cron job: check if provisioning instances are now ready."""
        provisioning = self.search([('state', '=', 'provisioning')])
        if not provisioning:
            return

        portal_url, api_key = self._get_portal_config() if provisioning else (None, None)
        if not api_key:
            return

        import requests as req
        try:
            r = req.get(
                f"{portal_url}/api/instances",
                headers={'X-API-Key': api_key},
                timeout=15,
            )
            r.raise_for_status()
            portal_instances = {i['name']: i for i in r.json()}
        except Exception as e:
            _logger.warning("Could not fetch portal instances: %s", e)
            return

        for instance in provisioning:
            portal_data = portal_instances.get(instance.name)
            if not portal_data:
                continue
            saas_status = portal_data.get('saas_status', '')
            if saas_status == 'ready' and portal_data.get('pod_status') == 'Running':
                instance.write({'state': 'running'})
                instance.message_post(body="✅ Instance is running and accessible!")
                # Send ready email
                template = self.env.ref(
                    'odoo_k8s_saas.mail_template_instance_ready',
                    raise_if_not_found=False,
                )
                if template:
                    template.send_mail(instance.id, force_send=True)

    def _provision_via_portal(self):
        """Send provisioning request to the SaaS Portal API.

        FIX: Payload now matches InstanceCreate schema exactly — includes
        admin_passwd, admin_email, admin_password (previously missing).
        """
        import requests as req
        import json as _json
        portal_url, api_key = self._get_portal_config()

        # Parse addons_repos JSON field
        try:
            repos = _json.loads(self.addons_repos or '[]')
            if isinstance(repos, str):
                repos = [{"url": repos, "branch": None}] if repos else []
        except Exception:
            repos = []

        payload = {
            'name': self.name,
            'domain': self.domain,
            'odoo_version': self.odoo_version,
            'db_password': self.db_password or 'odoo',
            'admin_passwd': self.admin_passwd,         # REQUIRED — was missing
            'admin_email': self.admin_email,           # REQUIRED — was missing
            'admin_password': self.admin_password,     # REQUIRED — was missing
            'lang': self.lang or 'en_US',
            'db_template': self.db_template or None,
            'addons_repos': repos,                     # FIX: list, not string
            'image': self.custom_image or None,
            'odoo_conf_overrides': {
                'workers': self.workers,
            },
        }
        try:
            r = req.post(
                f"{portal_url}/api/instances",
                json=payload,
                headers={'X-API-Key': api_key},
                timeout=30,
            )
            r.raise_for_status()
            self.write({
                'state': 'provisioning',
                'portal_response': r.text,
                'error_message': False,
            })
            self.message_post(body=f"✅ Provisioning started. URL: {self.url}")
        except Exception as e:
            self.write({'state': 'error', 'error_message': str(e)})
            self.message_post(body=f"❌ Provisioning failed: {e}")

    def _deprovision_via_portal(self):
        import requests as req
        portal_url, api_key = self._get_portal_config()
        try:
            req.delete(
                f"{portal_url}/api/instances/{self.name}",
                params={'domain': self.domain},
                headers={'X-API-Key': api_key},
                timeout=30,
            )
            self.message_post(body="🗑 Instance deleted from K3s.")
        except Exception as e:
            self.message_post(body=f"⚠ Delete request failed: {e}")
