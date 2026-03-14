from odoo import models, fields, api

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

    db_backup = fields.Selection(
        selection='_get_db_template_selection',
        string='DB Backup (ZIP)',
        help='Select an Odoo ZIP backup to restore. Leave empty for a fresh Odoo install.',
    )
    addons_repo = fields.Char('Addons Git Repo', help='https://github.com/org/repo.git')
    custom_image = fields.Char('Custom Image', help='e.g. ghcr.io/org/odoo-custom:18')
    db_password = fields.Char('DB Password', default='odoo', groups='base.group_system')

    workers = fields.Integer('Workers', default=2)
    admin_passwd = fields.Char(
        'Master Password',
        required=True,
        help='Odoo database manager master password for this instance.',
    )
    admin_email = fields.Char(
        'Admin Email',
        required=True,
        help='Login email for the Odoo admin user (used for fresh installs).',
    )
    admin_password = fields.Char(
        'Admin Password',
        required=True,
        help='Initial password for the Odoo admin user (used for fresh installs).',
    )
    lang = fields.Selection(
        selection=[
            ('en_US', 'English (US)'),
            ('es_ES', 'Spanish (ES)'),
            ('es_BO', 'Spanish (BO)'),
            ('pt_BR', 'Portuguese (BR)'),
        ],
        string='Language',
        default='en_US',
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
        self.ensure_one()
        self._provision_via_portal()

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
    def _get_db_template_selection(self):
        """Fetch available ZIP backup templates from the portal API."""
        import requests as req
        try:
            portal_url, api_key = self._get_portal_config()
            if not api_key:
                return []
            r = req.get(f"{portal_url}/api/templates",
                        headers={'X-API-Key': api_key}, timeout=5)
            r.raise_for_status()
            templates = r.json().get('templates', [])
            # Portal already filters to .zip — but filter here too for safety
            return [
                (t['key'], f"{t['key']} ({t['size_mb']} MB)")
                for t in templates if t['key'].endswith('.zip')
            ]
        except Exception:
            return []

    def _provision_via_portal(self):
        import requests as req
        portal_url, api_key = self._get_portal_config()
        template_key = self.db_backup or None
        master_pass = self.admin_passwd
        payload = {
            'name': self.name,
            'domain': self.domain,
            'odoo_version': self.odoo_version,
            'db_password': self.db_password or 'odoo',
            'db_template': template_key,
            'admin_passwd': self.admin_passwd,
            'admin_email': self.admin_email,
            'admin_password': self.admin_password,
            'lang': self.lang or 'en_US',
            'addons_repos': [{'url': self.addons_repo}] if self.addons_repo else [],
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
            self.message_post(body=f"✅ Instance provisioning started. URL: {self.url}")
            # Send "ready" email to customer
            template = self.env.ref('odoo_k8s_saas.mail_template_instance_ready', raise_if_not_found=False)
            if template:
                template.send_mail(self.id, force_send=True)
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

    def action_refresh_status(self):
        """Check instance status via portal API and update state."""
        self.ensure_one()
        self._check_portal_status()

    def _check_portal_status(self):
        """Query the portal API for pod status and update the record."""
        import requests as req
        portal_url, api_key = self._get_portal_config()
        if not api_key:
            return
        try:
            r = req.get(
                f"{portal_url}/api/instances/{self.name}",
                headers={'X-API-Key': api_key},
                timeout=15,
            )
            if r.status_code == 404:
                if self.state == 'provisioning':
                    self.write({'state': 'error', 'error_message': 'Instance not found on portal'})
                return
            r.raise_for_status()
            data = r.json()
            pods = data.get('pods', [])
            if pods:
                pod = pods[0]
                phase = pod.get('phase', '').lower()
                ready = pod.get('ready', False)
                if phase == 'running' and ready:
                    if self.state != 'running':
                        self.write({'state': 'running', 'error_message': False})
                        self.message_post(body="✅ Instance is running.")
                elif phase in ('failed', 'unknown'):
                    if self.state != 'error':
                        self.write({'state': 'error', 'error_message': f"Pod phase: {phase}"})
            self.write({'portal_response': r.text})
        except Exception as e:
            # Don't change state on transient network errors
            self.write({'portal_response': f"Status check failed: {e}"})

    @api.model
    def _cron_check_provisioning(self):
        """Cron: poll portal for all instances stuck in 'provisioning' state."""
        instances = self.search([('state', '=', 'provisioning')])
        for inst in instances:
            inst._check_portal_status()

