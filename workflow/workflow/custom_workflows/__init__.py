from os.path import dirname, basename, isfile, abspath
import glob
modules = glob.glob(dirname(abspath(__file__))+"/*/*.py")
print '1', dirname(abspath(__file__))
print '2', modules
__all__ = [ basename(f)[:-3] for f in modules if isfile(f)]
print '3', __all__

# import pkgutil
# import sys


# def load_all_modules_from_dir(dirname):
#     print 'here'
#     for importer, package_name, _ in pkgutil.iter_modules([dirname]):
#         print importer, package_name
#         full_package_name = '%s.%s' % (dirname, package_name)
#         print full_package_name
#         if full_package_name not in sys.modules:
#             module = importer.find_module(package_name
#                         ).load_module(full_package_name)
#             print module


# load_all_modules_from_dir('firmbase_ticket')