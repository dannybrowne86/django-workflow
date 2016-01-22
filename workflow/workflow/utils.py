from django.conf import settings
from workflow.defaults import WorkflowDefaults

def get_setting(name, **kwargs):
    """Returns the user-defined value for the setting, or a default value."""
    if hasattr(settings, name):  # Try user-defined settings first.
        return getattr(settings, name)
    if 'default' in kwargs:  # Fall back to a specified default value.
        return kwargs['default']
    if hasattr(defaults, name):  # If that's not given, look in defaults file.
        return getattr(defaults, name)
    msg = '{0} must be specified in your project settings.'.format(name)
    raise AttributeError(msg)