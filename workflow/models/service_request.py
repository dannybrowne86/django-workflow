from django.db import models
from .base_workflow import Ticket, TicketHistory

class ServiceRequest(Ticket):
    AC_STATUS = (
        ('aog', 'AOG'),
        ('mtx', 'Scheduled Maintenance'),
        ('other', 'Other (Provide in Description)')
    )
    CERTS = (
        ('far91', 'FAR 91'),
        ('far121', 'FAR 121'),
        ('far135', 'FAR 135'),
        ('other', 'Other (Provide in Description)'),
    )
    AC_MANUFACTURERS = (
        ('airbus', 'Airbus'),
        ('beechcraft', 'Beechcraft'),
        ('boeing', 'Boeing (including M-D)'),
        ('bombardier', 'Bombardier'),
        ('cessna', 'Cessna'),
        ('cirrus', 'Cirrus'),
        ('de_havilland', 'de Havilland'),
        ('embraer', 'Embraer'),
        ('falcon', 'Falcon'),
        ('fokker', 'Fokker'),
        ('gulfstream', 'Gulfstream'),
        ('iai', 'IAI'),
        ('mooney', 'Mooney'),
        ('northamerican', 'North American'),
        ('other', 'Other (Provide in Description)'),
        ('piper', 'Piper'),
    )
    AC_MODELS = (
        ('b717_200', 'B717-200'),
        ('b737_700', 'B737-700'),
        ('b737_800', 'B737-800'),
        ('b737_900er', 'B737-900ER'),
        ('b747_400', 'B747-400'),
        ('b757_200', 'B757-200'),
        ('b757_300', 'B757-300'),
        ('b767_300', 'B767-300'),
        ('b767_300er', 'B767-300ER'),
        ('b767_400er', 'B767-400ER'),
        ('b777_200er', 'B777-200ER'),
        ('b777_200lr', 'B777-200LR'),
        ('a319_100', 'A319-100'),
        ('a320_200', 'A320-200'),
        ('a330_200', 'A330-200'),
        ('a330_300', 'A330-300'),
        ('md_88', 'MD-88'),
        ('md_90', 'MD-90'),
        ('other', 'Other (Provide in Description)'),
    )

    contact_name = models.CharField(max_length=64, blank=True, null=True)
    contact_phone = models.CharField(max_length=16, blank=True, null=True)
    contact_email = models.CharField(max_length=128, blank=True, null=True,
        help_text='You can list multiple emails, separated by semicolons.')

    # operator defaults to business name
    operator = models.CharField(max_length=64)
    operating_cert_part = models.CharField(verbose_name='Operating Cert. Part', max_length=8, choices=CERTS)
    ac_status = models.CharField(max_length=8, choices=AC_STATUS, default='other')
    ac_location = models.CharField(max_length=64, help_text='Where was A/C when issue was discovered?')
    ac_manufacturer = models.CharField(max_length=16, choices=AC_MANUFACTURERS)
    ac_model = models.CharField(max_length=12, choices=AC_MODELS)
    ac_serial_number = models.CharField(max_length=32)
    ac_registration_number = models.CharField(max_length=32)
    ac_tail_number = models.CharField(blank=True, null=True, max_length=16)
    ac_flight_time = models.DecimalField(max_digits=9, decimal_places=2, help_text='A/C flight time (hours).')
    ac_cycles = models.PositiveIntegerField()

    # description = models.TextField(help_text='Describe the issue or damage requiring engineering disposition.')
    requested_action = models.TextField(help_text='Please provide the desired assistance/disposition.')
    response_required_by = models.DateTimeField(blank=True, null=True, help_text='Date "yyyy-mm-dd" (and time in UTC/GMT, optional) that a response is required by.')

    # same as response?
    disposition = models.TextField(null=True, blank=True)
    disposition_author = models.ForeignKey(User, related_name='rfe_disposition_author', blank=True, null=True)
    dispositioned_at = models.DateTimeField(blank=True, null=True)
    major = models.BooleanField(default=False, help_text='Major (checked) or Minor (unchecked)?')
    
    reviewer = models.ForeignKey(User, related_name='rfe_reviewer', blank=True, null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)


    def save(self, *args, **kwargs):
        super(ServiceRequest, self).save(*args, **kwargs)

        # create a historical record
        ServiceRequestHistory.objects.create(
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


class ServiceRequestHistory(models.Model):
    service_request = models.ForeignKey(ServiceRequest)
    type = models.CharField(max_length=12, choices=ServiceRequest.TYPES,
        default='bug')
    
    importance = models.FloatField(default=4.0, help_text='Provide a number '
        'indicating priority.  Lower numbers are higher priority.  For '
        'Critical tickets, considering setting this to <=1.0.')

    PROPOSAL_STATUS = ServiceRequest.PROPOSAL_STATUS
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