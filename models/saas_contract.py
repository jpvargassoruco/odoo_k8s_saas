# Copyright 2024 Aeisoftware
# License LGPL-3.0 or later.

from odoo import api, fields, models


class SaasInstance(models.Model):
    """Extend saas.instance to link it with an OCA contract."""

    _inherit = "saas.instance"

    contract_id = fields.Many2one(
        comodel_name="contract.contract",
        string="Contract",
        readonly=True,
        ondelete="set null",
        help="Recurring billing contract generated when the sale order was confirmed.",
    )
    contract_count = fields.Integer(
        compute="_compute_contract_count",
        string="Contracts",
    )

    @api.depends("contract_id")
    def _compute_contract_count(self):
        for record in self:
            record.contract_count = 1 if record.contract_id else 0

    def action_view_contract(self):
        """Open the linked contract form."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Contract",
            "res_model": "contract.contract",
            "view_mode": "form",
            "res_id": self.contract_id.id,
        }


class SaleOrder(models.Model):
    """Extend sale.order to auto-create a contract after provisioning."""

    _inherit = "sale.order"

    def _provision_saas_instance(self, line):
        """Create SaaS instance, then attach a recurring contract to it."""
        instance = super()._provision_saas_instance(line)
        if instance:
            contract = self._create_saas_contract(instance, line)
            instance.contract_id = contract
        return instance

    def _create_saas_contract(self, instance, line):
        """Create a monthly recurring contract.contract for a SaaS instance.

        The contract header drives recurrence for all lines (line_recurrence=False
        is the OCA default), so we set recurring_rule_type on the header and let
        the line inherit it via the computed field.

        price_unit on contract.line is computed from specific_price when
        automatic_price is False, so we write specific_price directly.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        product = line.product_id

        contract_vals = {
            "name": f"SaaS – {instance.name}",
            "code": self.name,  # stores the SO reference (e.g. S00042)
            "partner_id": self.partner_id.id,
            "contract_type": "sale",
            "date_start": today,
            "recurring_rule_type": "monthly",
            "recurring_interval": 1,
            "recurring_invoicing_type": "pre-paid",
            "note": (
                f"Auto-generated from sale order {self.name}.\n"
                f"SaaS instance: {instance.name} ({instance.domain})"
            ),
            "contract_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": line.name or product.display_name,
                        "quantity": line.product_uom_qty or 1.0,
                        "specific_price": line.price_unit,
                        "automatic_price": False,
                        "date_start": today,
                        "uom_id": product.uom_id.id,
                    },
                )
            ],
        }

        contract = self.env["contract.contract"].create(contract_vals)

        # Post a message on both the contract and the sale order for traceability.
        contract.message_post(
            body=f"Contract created automatically from sale order <b>{self.name}</b>."
        )
        self.message_post(
            body=(
                f"Recurring contract <b>{contract.name}</b> "
                f"created for SaaS instance <b>{instance.name}</b>."
            )
        )
        return contract
