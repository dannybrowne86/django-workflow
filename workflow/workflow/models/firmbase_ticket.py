from django.db import models
from .base_workflow import Ticket, TicketHistory

class FirmBaseTicket(Ticket):
    TYPES = (
        ('bug', 'Bug'),
        ('feature', 'New Feature'),
        ('help', 'General Inquiry'),
        ('admin', 'Admin Task')
    )
    type = models.CharField(max_length=12, choices=TYPES, default='bug')
    
    importance = models.FloatField(default=4.0, help_text='Provide a number '
        'indicating priority.  Lower numbers are higher priority.  For '
        'Critical tickets, considering setting this to <=1.0.')

    PROPOSAL_STATUS = (
        ('na', 'n/a'),
        ('pending', 'Pending'),
        ('countered', 'Countered'),
        ('approved', 'Approved')
    )
    proposed_ffp = models.DecimalField(
        verbose_name='Proposed Firm-Fixed-Price', default=0, max_digits=10,
        decimal_places=2, help_text='The Firm Fixed Price cost for the '
            'proposed work.')
    proposed_hours = models.DecimalField(verbose_name='T&M Proposed Hours',
        default=0, max_digits=10, decimal_places=2, help_text='The number of '
            'hours proposed to complete the work.')
    proposal_acceptance_due_date = models.DateField(blank=True, null=True,
        help_text='The proposal needs to be accepted by 2p CT on this date '
            'for the due date to be valid for the FFP estimate.')
    proposed_calendar_effort = models.PositiveIntegerField(default=0,
        help_text='The number of days <strong>after</strong> proposal '
            'acceptance the initial capability will be completed.')
    proposed_due_date = models.DateField(blank=True, null=True,
        help_text='The proposed work will be completed by 8a CT on this date, '
            'or AAC will receive a discount on the cost per agreed upon '
            'penalty schedule.')
    proposal_status = models.CharField(max_length=12, default="n/a")
    approver = models.ForeignKey(User, blank=True, null=True,
        related_name="firmbase_ticket_approver")
    approval_date = models.DateTimeField(blank=True, null=True)
    approval_comment = models.TextField(blank=True, null=True)


    def save(self, *args, **kwargs):
        super(FirmBaseTicket, self).save(*args, **kwargs)

        # create a historical record
        FirmBaseTicketHistory.objects.create(
            ticket=self,
            type=self.type,
            importance=self.importance,
            proposed_ffp=self.proposed_ffp,
            proposed_hours=self.proposed_hours,
            proposal_acceptance_due_date=self.proposal_acceptance_due_date,
            proposed_calendar_effort=self.proposed_calendar_effort,
            proposed_due_date=self.proposed_due_date,
            proposal_status=self.proposal_status,
            approver=self.approver,
            approval_date=self.approval_date,
            approval_comment=self.approval_comment
        )

    @property
    def get_importance_class(self):
        if self.importance <= 2.0 :
            return 'badge-important'
        elif self.importance <= 4.0:
            return 'badge-warning'
        elif self.importance <= 6.0:
            return 'badge-info'
        elif self.importance <= 8.0:
            return 'badge-success'
        else:
            return 'badge-inverse'


class FirmBaseTicketHistory(models.Model):
    firmbase_ticket = models.ForeignKey(FirmBaseTicket)
    type = models.CharField(max_length=12, choices=FirmBaseTicket.TYPES,
        default='bug')
    
    importance = models.FloatField(default=4.0, help_text='Provide a number '
        'indicating priority.  Lower numbers are higher priority.  For '
        'Critical tickets, considering setting this to <=1.0.')

    PROPOSAL_STATUS = FirmBaseTicket.PROPOSAL_STATUS
    proposed_ffp = models.DecimalField(
        verbose_name='Proposed Firm-Fixed-Price', default=0, max_digits=10,
        decimal_places=2, help_text='The Firm Fixed Price cost for the '
            'proposed work.')
    proposed_hours = models.DecimalField(verbose_name='T&M Proposed Hours',
        default=0, max_digits=10, decimal_places=2, help_text='The number of '
            'hours proposed to complete the work.')
    proposal_acceptance_due_date = models.DateField(blank=True, null=True,
        help_text='The proposal needs to be accepted by 2p CT on this date '
            'for the due date to be valid for the FFP estimate.')
    proposed_calendar_effort = models.PositiveIntegerField(default=0,
        help_text='The number of days <strong>after</strong> proposal '
            'acceptance the initial capability will be completed.')
    proposed_due_date = models.DateField(blank=True, null=True,
        help_text='The proposed work will be completed by 8a CT on this date, '
            'or AAC will receive a discount on the cost per agreed upon '
            'penalty schedule.')
    proposal_status = models.CharField(max_length=12, default="n/a")
    approver = models.ForeignKey(User, blank=True, null=True,
        related_name="firmbase_ticket_approver")
    approval_date = models.DateTimeField(blank=True, null=True)
    approval_comment = models.TextField(blank=True, null=True)