# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
import openerp.addons.decimal_precision as dp

class remise(models.Model):
    _name = 'scev.remise'

    date = fields.Date(string="Date", required=True,
            readonly=True, states={'draft' : [('readonly'), False]},
            default=fields.Date.today)

    user = fields.Many2one('res.users', string="Creator", required=True,
            readonly=True, states={'draft' : [('readonly'), False]},
            default=lambda self: self.env.user)

    ref = fields.Char(string="Reference", required=True, size=64,
            readonly=True, states={'draft' : [('readonly'), False]})

    journal = fields.Many2one('account.journal', string="Journal", required=True,
            readonly=True, states={'draft': [('readonly', False)]},
            domain=[('type', '=', 'cash')])

    move = fields.Many2one('account.move', string="Account move", required=True)

    period = fields.Many2one('account.period', string="Period", required=True,
            readonly=True, states={'draft': [('readonly', False)]})

    cheques = fields.One2many('scev.remise.line', 'remise_id', string="Cheques",
            readonly=True, states={'draft': [('readonly', False)]})

    amount = fields.Float(string="Amount", compute="_compute_amount",
            digits=dp.get_precision('Account'))

    nb_cheques = fields.Integer(string="Number of cheques",
            compute="_compute_nb_cheques")

    state = fields.Selection([ ('draft','Draft'),
        ('confirmed','Confirmed'), ('reconciled','Reconciled'),
        ('cancelled','Cancelled')], 'Status', readonly=True)

    @api.one
    @api.depends('cheques')
    def _compute_amount(self):
        self.amount = sum([c.amount for c in self.cheques])

    @api.one
    @api.depends('cheques')
    def _compute_nb_cheques(self):
        self.amount = len(self.cheques)

    @api.one
    def _get_name(self):
        return _("Cheque deposit %") % (self.ref,)

    @api.one
    def _prepare_move(self):
        return {
                'name': self._get_name(),
                'ref': self._get_name(),
                'date': self.date,
                'journal_id': self.journal.id,
                'period_id': self.period.id,
            }

    @api.one
    def _prepare_move_line_vals(self, move_id, amount, name):
        if amount > 0:
            credit = amount
            debit = 0.0
        else:
            credit = 0.0
            debit = -amount

        return {
                'name': name,
                'date': self.date,
                'ref': self._get_name(),
                'move_id': move_id,
                'account_id': account_id,
                'debit': debit,
                'credit': credit,
                'journal_id': self.journal.id,
                'period_id': self.period.id,
            }

    @api.one
    def _make_bank_move(self):
        # 1. créer account.move
        self.move = self.env['account.move'].create(self._prepare_move())

        # 2. créer pour chaque chèque un account.move_line
        for cheque in self.cheques:
            cheque.move_id = self.env['account.move.line'].create(
                    self._prepare_move_line_vals(self.move, cheque.amount,
                        cheque._get_name(), cheque.account_id))

        # 3. créer en contrepartie un account.move_line pour le total de la remise
        self.env['account.move.line'].create(self._prepare_move_line_vals(
                self.move, -self.amount, self._get_name(),
                self.journal.default_debit_account_id
            ))

    @api.one
    def _validate_remise(self):
        # Et maintenant, on réconcilie les entrées comptables avec leurs
        # factures quand il y a bien une facture.
        for cheque in self.cheques:
            if cheque.invoice_id:
                lines = self.env['account.move.line'].search([
                    ('account_id', '=', cheque.invoice_id.account_id),
                    ('move_id', 'in', (self.move, cheque.invoice_id.move_id)),
                    ])
                lines.reconcile_partial('manual')

    @api.one
    def test_all_cashed(self):
        # Tester si la remise de chèque a bien été validée en banque
        lines = self.env['account.move.line'].search([
            ('account_id', '=', self.journal.default_debit_account_id),
            ('move_id', '=', self.move)
            ])
        return all([l.reconcile_id for l in lines])

    ### Workflow stuff ###
    @api.one
    def action_draft(self):
        self.state = 'draft'

    @api.one
    def action_confirm(self):
        self._make_bank_move()
        self._validate_remise()
        self.state = 'confirmed'

    @api.one
    def action_reconciled(self):
        self.state = 'reconciled'

    @api.one
    def action_cancel(self):
        self.state = 'cancelled'


class remise_line(models.Model):
    _name = 'scev.remise.line'
    writer = fields.Char(string="Cheque writer", required=True)
    number = fields.Char(string="Cheque number", required=True)
    bank = fields.Char(string="Bank name", required=True)
    invoice_id = fields.Many2one('account.invoice', string="Invoice")
    amount = fields.Float(string="Amount", required=True,
            digits=dp.get_precision('Account'))
    account_id = fields.Many2one('account.account', string="Account to credit", required=True)
    move_id = fields.Many2one('account.move.line', string="Account move line")
    remise_id = fields.Many2one('scev.remise')

    @api.one
    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            self.amount = self.invoice_id.residual
            self.writer = self.invoice_id.partner_id.name
            self.account_id = self.invoice_id.account_id

    @api.one
    def _get_move_name(self):
        if self.invoice_id:
            self.name = _("Cheque %i (%) - Invoice %") % (self.writer,
                    self.number,
                    self.invoice_id.number)
        else:
            self.name = _("Cheque %i (%)") % (self.writer,
                    self.number)
