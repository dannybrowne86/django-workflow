from django.db import models
from .base_workflow import Ticket, TicketHistory

class PurchaseRequest(Ticket):
    TYPES = (
        ('it', 'IT / Computer'),
        ('office', 'Office Supplies'),
        ('project', 'Project Purchase'),
        ('other', 'Other')
    )
    type = models.CharField(max_length=12, choices=TYPES, default='office')

    # this optional link already exists in the base_workflow
    #project = models.ForeignKey(Project, blank=True, null=True,
    #    help_text='A Project is required for a project-related purchase request.')
    capital = models.BooleanField(default=False)
    amount = models.DecimalField(blank=True, null=True, max_digits=8, 
        decimal_places=2)

    budget_review_notes = models.TextField(blank=True, null=True)

    mgmt_approval = models.TextField(blank=True, null=True)
    mgmt_approver = models.ForeignKey(User,
        related_name='purchaserequest_mgmt_approver', blank=True, null=True)
    mgmt_approval_date = models.DateTimeField(blank=True, null=True)

    CARRIERS = (
        ('usps', 'USPS'),
        ('fedex', 'FedEx'),
        ('ups', 'UPS'),
        ('dhl', 'DHL'),
        ('other', 'Other'),
    )
    estimated_delivery_date = models.DateField(null=True, blank=True,
        help_text='When is the package scheduled to be delivered?')
    package_carrier = models.CharField(max_length=8, blank=True,
        choices=CARRIERS, help_text='Select the package delivery carrier.')
    tracking_number = models.CharField(max_length=64, blank=True,
        help_text='If available, provide the packing tracking number.')
    package_location = models.CharField(max_length=128, blank=True,
        help_text='Where was the package placed after it was delivered?')

    def save(self, *args, **kwargs):
        super(PurchaseRequest, self).save(*args, **kwargs)

        # create a historical record
        PurchaseRequestHistory.objects.create(
            purchase_request=self,
            type=self.type,
            capital=self.capital,
            amount=self.amount,
            budget_review_notes=self.budget_review_notes,
            mgmt_approval=self.mgmt_approval,
            mgmt_approver=self.mgmt_approver,
            mgmt_approval_date=self.mgmt_approval_date,
            estimated_delivery_date=self.estimated_delivery_date,
            package_carrier=self.package_carrier,
            tracking_number=self.tracking_number,
            package_location=self.package_location
        )


class PurchaseRequestHistory(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest)
    type = models.CharField(max_length=12, choices=PurchaseRequest.TYPES,
        default='office')
    capital = models.BooleanField(default=False)
    amount = models.DecimalField(blank=True, null=True, max_digits=8, 
        decimal_places=2)
    budget_review_notes = models.TextField(blank=True, null=True)
    mgmt_approval = models.TextField(blank=True, null=True)
    mgmt_approver = models.ForeignKey(User,
        related_name='purchaserequesthistory_mgmt_approver',
        blank=True, null=True)
    mgmt_approval_date = models.DateTimeField(blank=True, null=True)
    estimated_delivery_date = models.DateField(null=True, blank=True,
        help_text='When is the package scheduled to be delivered?')
    package_carrier = models.CharField(max_length=8, blank=True,
        choices=PurchaseRequest.CARRIERS,
        help_text='Select the package delivery carrier.')
    tracking_number = models.CharField(max_length=64, blank=True,
        help_text='If available, provide the packing tracking number.')
    package_location = models.CharField(max_length=128, blank=True,
        help_text='Where was the package placed after it was delivered?')
