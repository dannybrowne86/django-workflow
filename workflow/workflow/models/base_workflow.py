from django.contrib.postgres.fields import ArrayField
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.urlresolvers import reverse, reverse_lazy
from django.db import models
from django.db.models import Sum, Q

from timepiece.crm.models import UserProfile, Business, PaidTimeOffRequest, \
    Project, Lead
from timepiece.contracts.models import ProjectContract
from timepiece.entries.models import Entry

from taggit.managers import TaggableManager
from holidays.models import Holiday
import workdays

import boto
import calendar
import datetime
import hashlib
import random
from dateutil.relativedelta import relativedelta


class Workflow(models.Model):
    """A Workflow is the highest level concept which is the budget for
    capturing the States, Transitions, and custom fields for a workflow.
    In this context, a workflow is the combination of a form and a set of
    states/transitions for managing the work of a team, like a ticketing
    system.
    """

    name = models.CharField(max_length=64, help_text='This is the name of '
        'the workflow displayed in menus and navigation breadcrumbs.')
    short_name = models.CharField(max_length=8, help_text='This is the '
        'abbreviation used in the workflow ticket ID.')
    description = models.TextField(help_text='Provide a detailed description '
        'of what the workflow is used for managing.')

    def __unicode__(self):
        return self.name


class State(models.Model):
    """States capture the steps of a workflow.  The terminal flag determines
    whether a ticket in a state is considered open or closed.
    """
    # TODO: bootstrap 3 update  http://getbootstrap.com/components/#labels
    LABEL_STYLES = ( ('label', 'Grey'),
                     ('label label-success', 'Green'),
                     ('label label-warning', 'Gold'),
                     ('label label-important', 'Red'),
                     ('label label-info', 'Blue'),
                     ('label label-inverse', 'Black') )

    name = models.CharField(max_length=32)
    workflow = models.ForeignKey(Workflow, blank=True, null=True,
        help_text='Which workflow does this state exist in?')
    terminal = models.BooleanField(default=False, help_text='If a ticket is '
        'in this state, is that ticket terminated?  This is used to filter '
        'out closed/completed tickets.  If a transition exists out of this '
        'state, a ticket could be moved back into a non-terminal state.')
    label_style = models.CharField(max_length=32, choices=LABEL_STYLES, default='label')

    def __unicode__(self):
        return '%s' % (self.name)


class Transition(models.Model):
    """Transisitions provide the mapping from one state to another.
    Transitions provide a mechanism for determining who can execute a
    transition and who is notified upon the transition of a ticket.
    """
    DEFAULT_ASSIGNEE_TYPES = (
        ('creator', 'Change to Creator'),
        ('submitter', 'Change to Submitter'),
        ('default_assignee', 'Change to Specified User'),
        ('no_change', 'Do Not Change on Transition'),
        ('unassignee', 'Change to unassigned')
    )

    name = models.CharField(max_length=32)
    workflow = models.ForeignKey(Workflow, blank=True, null=True,
        help_text='Which workflows does this transition exist in?')
    start_state = models.ForeignKey(State, related_name='start',
        blank=True, null=True)
    end_state = models.ForeignKey(State, related_name='end')
    default_assignee_type = models.CharField(max_length=16,
        choices=DEFAULT_ASSIGNEE_TYPES,
        help_text='When this transition is executed, who do you want the '
        'ticket assigned to?')
    default_assignee = models.ForeignKey(User,
        related_name='generaltask_transition_default_assignee',
        help_text='If the Default Assignee Type is "Change to a Specific'
        'User", this field determines who that user is.',
        blank=True, null=True)
    notification_email_template = models.FileField(blank=True, null=True,
        upload_to='workflow-transition-email-templates', max_length=256)
    backup_notification_text = models.TextField(blank=True,
        help_text='For users that do not have HTML email, what is the backup '
            'text for the email?')
    button_type = models.CharField(max_length=32, default='', blank=True,
        null=True, help_text='Bootstrap v2.3.2 class name.')
    priority = models.PositiveSmallIntegerField(default=0,
        help_text='Larger numbers have higher likelihood it will appear first '
        'in a button list.')
    form = models.CharField(blank=True, null=True, default=None,
        max_length=64, help_text='What is the class name of the form to use '
        'for this transition?')

    # who can execute this transition?
    perms_all = models.BooleanField(default=False,
        help_text='All users can execute this transition.')
    perms_creator = models.BooleanField(default=False,
        help_text='The creator of the ticket can execute this transition.')
    perms_submitter = models.BooleanField(default=False,
        help_text='The submitter of the ticket can execute this transition.')
    perms_assginee = models.BooleanField(default=False,
        help_text='The currently assigned user can execute this transition.')
    perms_guardian = models.BooleanField(default=False,
        help_text='Reference the per-object permissions managed by'
        'django-guardian to determine who can execute this transition.')

    class Meta:
        permissions = (('execute_transition', 'Can execute transition.'),)

    def __unicode__(self):
        if self.start_state:
            return '%s: %s -> %s' % (self.name, self.start_state.name,
                self.end_state.name)
        else:
            return '%s: (start) -> %s' % (self.name, self.end_state.name)


class Ticket(models.Model):
    LOW = 'info'
    NORMAL = 'inverse' # TODO: change to primary with Bootstrap 3
    HIGH = 'warning'
    CRITICAL = 'important' # TODO: change to danger with Bootstrap 3
    PRIORITIES = (
        (LOW, 'Low'),
        (NORMAL, 'Normal'),
        (HIGH, 'High'),
        (CRITICAL, 'Critical')
    )
    
    workflow = models.ForeignKey(Workflow)
    form_id = models.CharField(default=None, max_length=64, blank=True)
    
    submitter = models.ForeignKey(User,
        help_text='The user that requested the submission of the ticket.')
    submitter_business = models.ForeignKey(Business,
        related_name='submitter_business')
    created_by = models.ForeignKey(User,
        help_text='The user that entered the ticket into the system.')
    last_user = models.ForeignKey(User, 
        help_text='The last user to modify the ticket in any way.')
    assignee = models.ForeignKey(User, blank=True,
        help_text='The user currently assigned to work on the ticket.')
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    scheduled = models.DateTimeField(verbose_name='Scheduled Date',
        blank=True, null=True)

    effort = models.DecimalField(max_digits=5, decimal_places=2, null=True,
        blank=True, verbose_name='Level of Effort', help_text='Estimate the '
            'number of hours required to complete the task.')
    mgmt_effort = models.DecimalField(max_digits=5, decimal_places=2, null=True,
        blank=True, verbose_name='Management Level of Effort Estimate',
        help_text='Management estimate of the number of hours required to '
            'complete the task.')
    priority = models.CharField(max_length=12, choices=PRIORITIES,
        default=NORMAL)

    fixed_due_date = models.DateField(verbose_name='Fixed Due Date',
        null=True, blank=True)
    relative_due_date_ticket = models.ForeignKey('self',
        verbose_name='Relative Due Date Linked Task',
        null=True, blank=True)
    relative_due_days_delta = models.IntegerField(
        verbose_name='Relative Due Date Days Delta', null=True, blank=True)
    cached_due_date = models.DateField(
        verbose_name='Due Date', null=True, blank=True)
    
    description = models.TextField()
    response = models.TextField(blank=True)
    status = models.ForeignKey(State,
        limit_choices_to=Q(workflow=self.workflow))
    
    # putting this here as ManyToMany because it would be bad practice to
    # add this to the Entry object within django-timepiece entries, imho
    entries = models.ManyToManyField(Entry, null=True, blank=True)
    users = models.ManyToManyField(User, null=True, blank=True)
    tags = TaggableManager()
    recurring_ticket = models.ForeignKey('RecurringTicket', null=True,
        blank=True)
    
    business = models.ForeignKey(Business, null=True, blank=True)
    contact = models.ForeignKey(Contact, null=True, blank=True)
    contract = models.ForeignKey(ProjectContract, null=True, blank=True)
    lead = models.ForeignKey(Lead, null=True, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True)
    document = models.ForeignKey(Document, null=True, blank=True)


    def __unicode__(self):
        return self.form_id

    def clean(self, *args, **kwargs):
        if self.fixed_due_date and self.relative_due_date_ticket:
            raise ValidationError('You cannot set both a Fixed Due Date and a '
                'Relative Due Date.')
        
        elif self.fixed_due_date and self.relative_due_days_delta:
            raise ValidationError('You cannot set both a Fixed Due Date and a '
                'Relative Due Date Days Delta.')
        
        elif self.fixed_due_date is None and self.relative_due_date_ticket \
            and self.relative_due_days_delta is None:

            raise ValidationError('To set a Relative Due Date set both the '
                'Relative Due Date Linked Task (the associated Ticket '
                'to delta the Due Date off of) and the Relative Due Date Days '
                'Delta (integer of difference between referenced Ticket '
                'Due Date and this tickets\'s due date).')
        
        elif self.fixed_due_date is None and (self.relative_due_date_ticket
            is None and self.relative_due_days_delta):
            raise ValidationError('To set a Relative Due Date set both the '
                'Relative Due Date Linked Task (the associated Ticket '
                'to delta the Due Date off of) and the Relative Due Date '
                'Days Delta (integer of difference between referenced Ticket '
                'Due Date and this tickets\'s due date).')
        
        elif self.fixed_due_date is None and \
            self.relative_due_date_ticket is None and \
            self.relative_due_days_delta is None:

            raise ValidationError('You must set either a Fixed Due Date or '
                'both a Relative Due Date General Task (the associated '
                'General Task to delta the Due Date off of) and Relative Due '
                'Date Days Delta (integer of difference between referenced '
                'General Task Due Date and this task\'s due date).')

        # if relative due date selected, be sure there is no cycle introduced
        if self.fixed_due_date is None and self.id is not None:
            current_ticket = self.relative_due_date_ticket
            while current_ticket.fixed_due_date is None:
                if current_ticket.id == self.id:
                    # should not get here, because the circular reference will
                    # have the old fixed date, perhaps, therefore need the
                    # second check outside the while
                    raise ValidationError('With the selected Relative Due '
                        'Date Ticket you will introduce a Due Date '
                        'reference cylce.  Select a different General Task '
                        'or set a Fixed Due Date.')
                current_ticket = current_ticket.relative_due_date_ticket

            if current_ticket.id == self.id:
                raise ValidationError('With the selected Relative Due '
                        'Date Ticket you will introduce a Due Date '
                        'reference cylce.  Select a different General Task '
                        'or set a Fixed Due Date.')

    def set_cached_due_date(self):
        if self.fixed_due_date:
            self.cached_due_date = self.fixed_due_date
        else:
            delayed_days = self.relative_due_days_delta
            delta = 1 if self.relative_due_days_delta >= 0 else -1
            dates = [datetime.date.today(),
                datetime.date.today() + relativedelta(days=2*delayed_days)]
            holidays = Holiday.holidays_between_dates(min(dates), max(dates))
            
            if self.relative_due_date_ticket.cached_due_date is None:
                # we want to recursively call this to make sure everything is
                # up to date when we are setting a cached value
                self.relative_due_date_ticket.set_cached_due_date()

            due_date = self.relative_due_date_ticket.cached_due_date
            while delayed_days != 0:
                due_date = due_date + relativedelta(days=delta)
                if due_date not in holidays and due_date.weekday() < 5:
                    delayed_days  -= delta

            self.cached_due_date = due_date
        # self.save()
        # whatever calls this should do the save (if that is desired)

    @property
    def requested_date(self):
        if self.cached_due_date is None:
            self.set_cached_due_date()
            self.save()
        return self.cached_due_date

    @property
    def hours_spent(self):
        return self.entries.all().aggregate(Sum('hours'))['hours__sum'] or 0.0
    
    @property
    def overdue(self):
        if (self.cached_due_date - datetime.date.today()).days <= 0:
            return (self.cached_due_date - datetime.date.today()).days
        else:
            return 1

    @property
    def past_due(self):
        return self.cached_due_date <= datetime.date.today()

    @property
    def available_hours(self):
        end_date = self.cached_due_date
        if end_date is None or self.effort is None:
            # TODO: what is an appropriate amount of effort (man-days) to set
            #       for a task that has no effort or no due date?  Right now
            #       we set at 2 hours (a quarter-day)
            return 0.25 # or 0.0?
        else:
            if type(end_date) is datetime.datetime:
                end_date = end_date.date()
            # get holidays in years covered across today through
            # requested/scheduled date
            holidays = []
            ptor_time = 0.0
            for year in range(datetime.date.today().year, end_date.year+1):
                holiday_dates = [h['date'] for h in Holiday.get_holidays_for_year(year, {'paid_holiday':True})]
                holidays.extend(holiday_dates)
            
                # also add paid time off requests that have been approved as non working days
                if self.assignee:
                    for ptor in PaidTimeOffRequest.objects.filter(Q(pto_start_date__year=year)|Q(pto_end_date__year=year)
                        ).filter(Q(status=PaidTimeOffRequest.APPROVED)|Q(status=PaidTimeOffRequest.PROCESSED)
                        ).filter(user_profile=self.assignee.profile):
                        for i in range((ptor.pto_end_date-ptor.pto_start_date).days):
                            holidays.append(ptor.pto_start_date+datetime.timedelta(days=i))
                        if float(ptor.amount) < 8.0:
                            ptor_time += 8.0 - float(ptor.amount)

            # get number of workdays found in between the today and end_date
            num_workdays = workdays.networkdays(datetime.date.today(),
                                                end_date,
                                                holidays)
            num_workdays = num_workdays - (float(ptor_time)/8.0)
            return 8.0 * max(0.5,num_workdays)

    @property
    def remaining_effort(self):
        try:
            return max(1.0, float(self.effort) - float(self.hours_spent))
        except:
            return 1.0

    @property
    def hours_per_whole_day(self):
        min_days = max(self.available_hours / 8.0, 1.0)
        return max(self.remaining_effort/min_days, 1.0)

    @property
    def hours_per_day(self):
        min_days = self.available_hours / 8.0
        return max(self.remaining_effort/min_days, 1.0)

    @property
    def priority_scale(self):
        if self.priority == self.LOW:
            return get_setting('WORKFLOW_LOW_PRIORITY_SCALING_FACTOR')
        elif self.priority == self.NORMAL:
            return get_setting('WORKFLOW_NORMAL_PRIORITY_SCALING_FACTOR')
        elif self.priority == self.HIGH:
            return get_setting('WORKFLOW_HIGH_PRIORITY_SCALING_FACTOR')
        elif self.priority == self.CRITICAL:
            return get_setting('WORKFLOW_CRITICAL_PRIORITY_SCALING_FACTOR')
        else:
            return get_setting('WORKFLOW_DEFAULT_PRIORITY_SCALING_FACTOR')
    
    @property
    def weighted_priority(self):
        # min_days_remaining = max((self.cached_due_date-datetime.date.today()).days, 0.5)
        return 0.9**((self.available_hours/self.hours_per_day) - self.priority_scale) + 1
        #return self.priority_scale * self.hours_per_day

    def get_unique_id(self, workflow=None, time=None, business=None):
        if workflow is None:
            workflow = self.workflow
        if time is None:
            time = self.created_at
        if business is None:
            business = self.submitter_business
        count = len(Ticket.objects.filter(created_at__year=time.year,
                                          business=business,
                                          created_at__lte=time,
                                          workflow=workflow))
        return "%s-%s-%d-%04d" % (self.workflow.short_name,
                                  business.short_name,
                                  time.year,
                                  count+1)

    def save(self, *args, **kwargs):
        if self.form_id is None:
            user_profile = UserProfile.objects.get(user=self.created_by)
            self.submitter_business = user_profile.business
            
            self.form_id = self.get_unique_id(workflow=self.workflow,
                time=self.created_at, business=self.business)
            self.users.add(self.created_by)
            self.users.add(self.submitter)
            if self.assignee:
                self.users.add(self.assignee)
        
        super(Ticket, self).save(*args, **kwargs)

        # create a historical record
        TicketHistory.objects.create(
            ticket=self,
            workflow=self.workflow,
            form_id=self.form_id,
            submitter=self.submitter,
            submitter_business=self.submitter_business,
            created_by=self.created_by,
            last_user=self.last_user,
            assignee=self.assignee,
            created_at=self.created_at,
            last_activity=self.last_activity,
            scheduled=self.scheduled,
            effort=self.effort,
            mgmt_effort=self.mgmt_effort,
            priority=self.priority,
            fixed_due_date=self.fixed_due_date,
            relative_due_date_ticket=self.relative_due_date_ticket,
            relative_due_days_delta=self.relative_due_days_delta,
            cached_due_date=self.cached_due_date,
            description=self.description,
            response=self.response,
            status=self.status,
            recurring_ticket=self.recurring_ticket,
            business=self.business,
            contact=self.contact,
            contract=self.contract,
            lead=self.lead,
            project=self.project,
            document=self.document
        )

    def get_absolute_url(self):
        return reverse('view_workflow_ticket', args=(self.id,))

    @property
    def next_actions(self):
        return Transition.objects.filter(workflow=self.workflow, 
            start_state=self.status, start_state__terminal=False
            ).order_by('-priority')

    @property
    def reopen_actions(self):
        return Transition.objects.filter(workflow=self.workflow,
            start_state=self.status, start_state__terminal=True
            ).order_by('-priority')

    @property
    def get_notes(self):
        return TicketNote.objects.filter(ticket=self).order_by('-created_at')

    @property
    def get_attachments(self):
        return TicketAttachment.objects.filter(ticket=self
            ).order_by('upload_utc')

    @property
    def get_total_hours(self):
        return self.entries.all().aggregate(Sum('hours'))['hours__sum'] or 0


class RecurringTicket(models.Model):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    NTH_WEEKDAY = 'nth_weekday'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'
    REPEAT = (('', 'One Time'),
              (DAILY, 'Daily'),
              (WEEKLY, 'Weekly'),
              (NTH_WEEKDAY, 'Nth Weekday'),
              (MONTHLY, 'Monthly'),
              (YEARLY, 'Yearly'))
    ORDINALS = ((1, 'First'),
                (2, 'Second'),
                (3, 'Third'),
                (4, 'Fourth'),
                (5, 'Last'))
    END = (('never', 'Never'),
           ('date', 'On Date'),
           ('num_occurrences', 'After [n] occurrences'))
    TIME_UNITS = (('day', 'day(s)'),
                  ('week', 'week(s)'),
                  ('month', 'month(s)'),
                  ('year', 'year(s)'))
    DAYS_OF_MONTH = tuple((i, i) for i in range(1,29) + ['Last'])
    INTERVAL_DATE = ((0, 'Repeat interval sets date ticket is *created*.'),
                     (1, 'Repeat interval sets date ticket is *due*.'))

    name = models.CharField(max_length=64,
        help_text='This is a name to identify the recurring ticket.')
    form_id = models.CharField(max_length=32, null=True, blank=True)
    description = models.TextField(
        help_text='Description of this recurring ticket.')
    submitter = models.ForeignKey(User,
        related_name='recurring_ticket_submitter', help_text='The user that you '
        'want listed as the submitter on the created tickets.')
    created_by = models.ForeignKey(User,
        related_name='recurring_ticket_created_by',
        help_text='The user that created this recurring ticket.')
    created_at = models.DateTimeField(auto_now_add=True)
    last_user = models.ForeignKey(User,
        related_name='recurring_ticket_last_user',
        help_text='The user last edited the recurring ticket.')
    last_activity = models.DateTimeField(auto_now=True)
    active = models.BooleanField(default=True,
        help_text='To disable a recurring ticket (keep it from creating new '
            'tickets), unselect this checkbox.')
    deleted = models.BooleanField(default=False,
        help_text='To hide the recurring ticket from the front-end, '
            'select this option.')
    
    ticket_description = models.TextField(
        help_text='Text to place in the created ticket description.')
    ticket_assignee = models.ForeignKey(User,
        related_name='recurring_ticket_assignee',
        help_text='The default assignee for the ticket to be created.')
    ticket_effort = models.DecimalField(max_digits=5, decimal_places=2,
        null=True, blank=True, verbose_name='Level of Effort',
        help_text='Estimate the number of hours required to complete the '
            'ticket.')
    ticket_priority = models.CharField(max_length=12,
        choices=Ticket.PRIORITIES, default=Ticket.NORMAL,
        help_text='The priority of the tickets to be created.')

    last_ticket_created = models.DateField(null=True, blank=True,
        help_text='The date of last time a ticket was created from this '
        'recurring item.')
    next_ticket_created = models.DateField(null=True, blank=True,
        help_text='The next date a ticket should be created from this '
        'recurring item.')

    # this is when the ticket will be created
    interval_for_due = models.PositiveSmallIntegerField(
        verbose_name='Repeat interval sets...',
        choices=INTERVAL_DATE, default=0)
    repeat_type = models.CharField(choices=REPEAT, max_length=16)
    repeat_interval_type = models.PositiveSmallIntegerField(choices=ORDINALS,
        null=True, blank=True)
    repeat_interval = models.PositiveIntegerField(
        help_text='1 means "every".  2 means "every other."  Etc.')
    start_date = models.DateField(
        help_text='Select the date you want to start the repeat interval. '
        'This needs to be today or in the future.')
    end_condition = models.CharField(choices=END, max_length=16,
        help_text='When do you want tickets to no longer be automatically '
            'created?')
    end_date = models.DateField(null=True, blank=True,
        help_text='If End Condition is "On Date", enter the date here.')
    after = models.PositiveSmallIntegerField(null=True, blank=True,
        help_text='If End Condition is "After [n] occurences", enter a '
            'positive Integer here.')
    weekdays = models.CommaSeparatedIntegerField(max_length=16, null=True,
        blank=True)
    days_of_month = models.CommaSeparatedIntegerField(max_length=100,
        null=True, blank=True)

    due_date_unit = models.CharField(max_length=8, choices=TIME_UNITS)
    due_date_interval = models.PositiveSmallIntegerField()

    limit_to_one_active_ticket = models.BooleanField(default=True,
        help_text='If you do not want to have a new ticket automatically '
        'created if there is still one open, select this option.')
    
    class Meta:
        ordering = ('form_id',)

    def __unicode__(self):
        return '%s - %s' % (self.form_id, self.name)

    @property
    def get_notes(self):
        return self.recurringticketnote_set.all().order_by('-created_at')

    @property
    def get_weekdays(self):
        return [int(wd) for wd in self.weekdays.split(',')]

    @property
    def get_month_days(self):
        try:
            return [int(dom) for dom in self.days_of_month.split(',')]
        except:
            return self.days_of_month.split(',')

    def get_current_month_days(self, next_date):
        days_of_month = []
        for dom in self.days_of_month.split(','):
            if dom == 'Last':
                days_of_month.append(calendar.monthrange(next_date.year, next_date.month)[1])
            else:
                days_of_month.append(int(dom))
        return days_of_month

    @property
    def ordinal(self):
        if self.repeat_interval_type:
            return int(self.repeat_interval_type)
        else:
            return None

    def create_ticket(self):
        # check that there has not been one submitted on the same day
        ticket = Ticket.objects.filter(recurring_ticket=self, 
            created_at__startswith=datetime.date.today())
        if ticket.count() == 1:
            return ticket[0]
        elif ticket.count() > 0:
            # TODO: perhaps raise an exception
            return ticket

        # there is going to be an update
        # self.last_user = User.objects.get(id=4)            

        # if we only want 1 active ticket, check to see if there's others
        # already open
        if self.limit_to_one_active_ticket:
            if Ticket.objects.filter(recurring_ticket=self,
                status__terminal=False).count():
                # do not create another one, but update the future date
                self.next_ticket_created = self.get_next_day()
                self.save()
                return Ticket.objects.filter(recurring_ticket=self,
                    status__terminal=False).order_by('-created_at')[0]


        kwarg = {'%ss'%self.due_date_unit: self.due_date_interval}
        due_date = datetime.date.today() + relativedelta(**kwarg)

        ticket = Ticket(created_by=self.created_by if \
            self.created_by.is_active else self.last_user,
                         submitter=self.submitter,
                         last_user=self.last_user,
                         assignee=self.ticket_assignee,
                         effort=self.ticket_effort,
                         priority=self.ticket_priority,
                         fixed_due_date=due_date,
                         description=self.ticket_description,
                         recurring_ticket=self)
        ticket.save()
        
        # set that last ticket created to today
        self.last_ticket_created = datetime.date.today()
        # determine when the next ticket should be created and save that date
        self.next_ticket_created = self.get_next_day()
        self.save()

        return ticket

    def get_next_day(self):
        """Based on the recurrence pattern defined in the instance,
        this function determines when the next occurence should be.
        """
        # assumes that today is not an option
        next_date = datetime.date.today()
        if self.last_ticket_created:
            kwarg = {'%ss'%self.due_date_unit: self.due_date_interval}
            next_date = self.last_ticket_created + relativedelta(**kwarg) + \
                relativedelta(days=1)
        
        next_date = max(next_date, datetime.date.today() + datetime.timedelta(days=1))

        if self.repeat_type == '':
            # if there is no recurrence, simply return the one-time date
            return self.start_date

        elif self.repeat_type == self.DAILY:
            # make sure it is not a weekend or a holiday
            while ((next_date.weekday() >= 5) or 
                   (Holiday.is_paid_holiday(next_date))):
                next_date += datetime.timedelta(days=1)

        elif self.repeat_type == self.WEEKLY:
            # TODO: only works for repeat_interval 1 right now
            while ((next_date.weekday() not in self.get_weekdays) or 
                   (next_date.weekday() >= 5)):
                next_date += datetime.timedelta(days=1)
            
            # after matching the recurrence pattern, make sure it
            # is not a holiday.  If it is, back track to the first
            # working day
            if Holiday.is_paid_holiday(next_date):
                while ((next_date.weekday() >= 5) or 
                   (Holiday.is_paid_holiday(next_date))):
                    next_date -= datetime.timedelta(days=1)

        elif self.repeat_type == self.MONTHLY:
            # TODO: only works for repeat_interval 1 right now
            while next_date.day not in self.get_current_month_days(next_date) or next_date < datetime.date.today():
                next_date += datetime.timedelta(days=1)
            
            # after matching the recurrence pattern, make sure it
            # is not a holiday.  If it is, back track to the first
            # working day
            if Holiday.is_paid_holiday(next_date):
                while ((next_date.weekday() >= 5) or 
                   (Holiday.is_paid_holiday(next_date))):
                    next_date -= datetime.timedelta(days=1)

        elif self.repeat_type == self.NTH_WEEKDAY:
            dow = self.get_weekdays[0]
            if self.last_ticket_created:
                next_date = self.last_ticket_created.replace(day=1)
                for i in range(self.repeat_interval):
                    next_date = (next_date + datetime.timedelta(days=31)).replace(day=1)
            else:
                next_date = next_date.replace(day=1)

            if self.ordinal < 5:
                count = 0
                while count < self.ordinal:
                    if next_date.weekday() == dow:
                        count += 1
                    next_date += relativedelta(days=1)
                next_date -= relativedelta(days=1)
                
            else:
                next_date = datetime.date(next_date.year, next_date.month, 
                    calendar.monthrange(next_date.year,next_date.month)[1])
                while next_date.weekday() != dow:
                    next_date -= relativedelta(days=1)
            
            if next_date > datetime.date.today():
                pass
            else:
                self.last_ticket_created = next_date
                self.save()
                return self.get_next_day()

        elif self.repeat_type == self.YEARLY:
            # TODO: only works for repeat_interval 1 right now
            if self.last_ticket_created:
                # TODO: this should be more robust to not use the last_ticket_created date
                next_date = self.last_ticket_created + relativedelta(years=1)

            else:
                next_date = self.start_date

        # if the interval is intended for the Due Date as opposed
        # to the create date, push the next_date back
        if self.interval_for_due == 1:
            kwarg = {'%ss'%self.due_date_unit: self.due_date_interval}
            next_date -= relativedelta(**kwarg)

        return  next_date

    def get_unique_id(self, time=None, business='+++'):
        if time is None:
            time = self.created_at
        count = len(RecurringTicket.objects.filter(
            created_at__year=time.year,
            created_at__lte=time))
        return "%s-R-%s-%s-%03d" % (
            self.workflow.short_name,
            business,
            time.strftime('%y'),
            count)

    def save(self, *args, **kwargs):
        user_profile = UserProfile.objects.get(user=self.created_by)
        super(RecurringTicket, self).save(*args, **kwargs)
        today = datetime.date.today()
        if self.form_id is None:
            self.form_id = self.get_unique_id(time=self.created_at,
                business=user_profile.business.short_name)
            self.save()

        no_current_tickets = not(bool(self.generalticket_set.filter(
            status__terminal=False).count()))

        if ((self.repeat_type == self.DAILY) and
            no_current_tickets and
            (today.weekday()<=4) and
            (not Holiday.is_holiday(today))):

            self.create_general_ticket()

        elif ((self.repeat_type == self.WEEKLY) and 
            no_current_tickets and
            (today.weekday() in self.get_weekdays) and
            (not Holiday.is_holiday(today))):

            self.create_general_ticket()

        elif ((self.repeat_type == self.MONTHLY) and
            no_current_tickets and
            (today.day in self.get_month_days) and
            (not Holiday.is_holiday(today))):

            self.create_general_ticket()

        elif ((self.repeat_type == self.NTH_WEEKDAY) and
            no_current_tickets and
            (today.weekday() in self.get_weekdays) and
            (not Holiday.is_holiday(today))):

            # do a second check to make sure Ordinal matches
            count = 0
            d = today.replace(day=1)
            while d <= today:
                if d.weekday() in self.get_weekdays:
                    count += 1
            if count == self.ordinal:
                self.create_general_ticket()

        elif ((self.repeat_type == self.YEARLY) and
            no_current_tickets and
            (today == self.start_date)):

            self.create_general_ticket()

        else:
            # determine when the next ticket should be created and save that date
            self.next_task_created = self.get_next_day()
            if self.next_task_created < datetime.date.today():
                self.create_general_task()
            super(RecurringTicket, self).save(*args, **kwargs)
            

    # this should be run daily with a cron job
    @classmethod
    def create_tickets(cls, date=datetime.date.today()):
        for rt in RecurringTicket.objects.filter(active=True, next_task_created=date):
            rt.create_general_task()

    def ordinal_display(self, num):
        # provides ordinal number up to 31st
        try:
            num = int(num)
            suffixes = ["th", "st", "nd", "rd", ] + ["th"] * 17 + ["st", "nd", "rd", ] + ["th"] * 7 + ["st"]
            return str(num) + suffixes[num % 100]
        except:
            return num

    @property
    def recurrence_display(self):
        s = 'Due ' if self.interval_for_due else 'Created '
        if self.repeat_type == self.DAILY:
            s += 'every work day.'

        elif self.repeat_type == self.WEEKLY:
            if self.repeat_interval == 1:
                s += 'every week'
            elif self.repeat_interval == 2:
                s += 'every other week'
            else:
                s += 'every ' + self.ordinal_display(self.repeat_interval) + ' week'
            s += ' on '
            for wd in self.weekdays.split(','):
                s += calendar.day_name[int(wd)] + ', '
            s = s[:-2] + '.'

        elif self.repeat_type == self.MONTHLY:
            if self.repeat_interval == 1:
                s += 'every month'
            elif self.repeat_interval == 2:
                s += 'every other month'
            else:
                s += 'every ' + self.ordinal_display(self.repeat_interval) + ' month'
            s += ' on the '
            if self.repeat_interval_type and len(self.weekdays)==1:
                s += '%s %s--' % (self.get_repeat_interval_type_display(), calendar.day_name[int(self.weekdays)])
            elif self.days_of_month:
                for dom in self.days_of_month.split(','):
                    s += self.ordinal_display(dom) + ', '
            s = s[:-2] + '.'

        elif self.repeat_type == self.NTH_WEEKDAY:
            if self.repeat_interval == 1:
                s += 'every month'
            elif self.repeat_interval == 2:
                s += 'every other month'
            else:
                s += 'every ' + self.ordinal_display(self.repeat_interval) + ' month'
            s += ' on the '
            if self.repeat_interval_type and len(self.weekdays)==1:
                s += '%s %s--' % (self.get_repeat_interval_type_display(), calendar.day_name[int(self.weekdays)])
            elif self.days_of_month:
                for dom in self.days_of_month.split(','):
                    s += self.ordinal_display(dom) + ', '
            s = s[:-2] + '.'

        elif self.repeat_type == '':
            s += 'one time on %s.' % (self.start_date)

        elif self.repeat_type == self.YEARLY:
            if self.repeat_interval == 1:
                s += 'every year on '
            elif self.repeat_interval == 2:
                s += 'every other year on '
            else:
                s += 'every ' + self.ordinal_display(self.repeat_interval) + ' year on '
            s += self.start_date.strftime('%B ') + \
                 self.ordinal_display(self.start_date.day) + '.'

        else:
            return 'n/a'

        return s


class TicketHistory(models.Model):
    ticket = models.ForeignKey(Ticket)
    workflow = models.ForeignKey(Workflow)
    form_id = models.CharField(max_length=64)
    
    submitter = models.ForeignKey(User,
        help_text='The user that requested the submission of the ticket.')
    submitter_business = models.ForeignKey(Business,
        related_name='submitter_business')
    created_by = models.ForeignKey(User,
        help_text='The user that entered the ticket into the system.')
    last_user = models.ForeignKey(User, 
        help_text='The last user to modify the ticket in any way.')
    assignee = models.ForeignKey(User, blank=True,
        help_text='The user currently assigned to work on the ticket.')
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    scheduled = models.DateTimeField(verbose_name='Scheduled Date',
        blank=True, null=True)
    
    effort = models.DecimalField(max_digits=5, decimal_places=2, null=True,
        blank=True, verbose_name='Level of Effort', help_text='Estimate the '
            'number of hours required to complete the task.')
    mgmt_effort = models.DecimalField(max_digits=5, decimal_places=2, null=True,
        blank=True, verbose_name='Management Level of Effort Estimate',
        help_text='Management estimate of the number of hours required to '
            'complete the task.')
    priority = models.CharField(max_length=12, choices=Ticket.PRIORITIES,
        default=Ticket.NORMAL)
    
    fixed_due_date = models.DateField(verbose_name='Fixed Due Date',
        null=True, blank=True)
    relative_due_date_ticket = models.ForeignKey(Ticket,
        verbose_name='Relative Due Date Linked Task',
        null=True, blank=True)
    relative_due_days_delta = models.IntegerField(
        verbose_name='Relative Due Date Days Delta', null=True, blank=True)
    cached_due_date = models.DateField(
        verbose_name='Due Date', null=True, blank=True)
    
    description = models.TextField()
    response = models.TextField(blank=True)
    status = models.ForeignKey(State)
    
    recurring_ticket = models.ForeignKey('RecurringTicket', null=True,
        blank=True)
    
    business = models.ForeignKey(Business, null=True, blank=True)
    contact = models.ForeignKey(Contact, null=True, blank=True)
    contract = models.ForeignKey(ProjectContract, null=True, blank=True)
    lead = models.ForeignKey(Lead, null=True, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True)
    document = models.ForeignKey(Document, null=True, blank=True)

    def __unicode__(self):
        return '%s (%s)' % (str(self.ticket), self.last_activity)


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket)
    ticket_temp_id = models.CharField(max_length=32, blank=True, null=True)
    bucket = models.CharField(max_length=64)
    uuid = models.TextField() # AWS S3 uuid
    filename = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User)
    description = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at',)

    def __unicode__(self):
        return "%s: %s" % (str(self.ticket), self.filename)

    def get_s3_file_path(self):
        conn = boto.connect_s3(settings.AWS_UPLOAD_CLIENT_KEY,
            settings.AWS_UPLOAD_CLIENT_SECRET_KEY)
        bucket = conn.get_bucket(self.bucket)
        return bucket.get_key(self.uuid)

    def get_download_url(self):
        s3_file_path = self.get_s3_file_path()
        url = s3_file_path.generate_url(expires_in=10)
        # expiry time is in seconds
        return url

    def delete(self):
        try:
            s3_file_path = self.get_s3_file_path()
            s3_file_path.delete()
        except:
            # log this error
            pass
        super(TicketAttachment, self).delete()


class TicketNote(models.Model):
    ticket = models.ForeignKey(Ticket)
    created_by = models.ForeignKey(User)
    created_at = models.DateTimeField(auto_now_add=True)
    edited = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    parent = models.ForeignKey("self", null=True, blank=True)
    text = models.TextField()

    def get_thread(self, thread):
        thread.append(self)
        for n in GeneralTaskNote.objects.filter(parent=self).order_by('-created_at'):
            thread.append(n.get_thread(), thread)

    def save(self, *args, **kwargs):
        super(TicketNote, self).save(*args, **kwargs)
        # TODO: change to get this from settings.
        url = 'https://firmbase.aacengineering.com%s' % (reverse('view_workflow_ticket', args=(self.ticket.id,)))
        # TODO: allow users to subscribe to feeds
        # general_task_emails.new_note(self, url, Group.objects.get(name=GeneralTask.RESPONSIBLE_GROUP))


class RecurringTicketNote(models.Model):
    recurring_ticket = models.ForeignKey(RecurringTicket)
    created_by = models.ForeignKey(User)
    created_at = models.DateTimeField(auto_now_add=True)
    edited = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    parent = models.ForeignKey("self", null=True, blank=True)
    text = models.TextField()
