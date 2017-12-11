# -*- coding: utf-8 -*-
"""Helper for building projects from source."""

from __future__ import print_function
from __future__ import unicode_literals

import fileinput
import glob
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import zipfile

from l2tdevtools import dpkg_files
from l2tdevtools import download_helper
from l2tdevtools import py2to3
from l2tdevtools import source_helper
from l2tdevtools import spec_file


class BuildHelper(object):
  """Helper to build projects from source."""

  LOG_FILENAME = 'build.log'

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(BuildHelper, self).__init__()
    self._data_path = os.path.join(l2tdevtools_path, 'data')
    self._project_definition = project_definition

  def _IsPython2Only(self):
    """Determines if the project only supports Python version 2.

    Note that Python 3 is supported as of 3.4 any earlier version is not
    seen as compatible.

    Returns:
      bool: True if the project only support Python version 2.
    """
    return 'python2_only' in self._project_definition.build_options

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    build_dependencies = self._project_definition.build_dependencies
    if not build_dependencies:
      build_dependencies = []
    return list(build_dependencies)

  def CheckBuildRequired(self, unused_source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    return True


class DPKGBuildHelper(BuildHelper):
  """Helper to build dpkg packages (.deb).

  Attributes:
    architecture (str): dpkg target architecture.
    distribution (str): dpkg target distributions.
    version_suffix (str): dpkg version suffix.
  """

  _BUILD_DEPENDENCIES = frozenset([
      'git',
      'build-essential',
      'autotools-dev',
      'autoconf',
      'automake',
      'autopoint',
      'dh-autoreconf,',
      'libtool',
      'gettext',
      'flex',
      'byacc',
      'debhelper',
      'devscripts',
      'dpkg-dev',
      'fakeroot',
      'quilt',
      'python-all',
      'python-all-dev',
      'python-setuptools',
      'python3-all',
      'python3-all-dev',
      'python3-setuptools',
  ])

  _BUILD_DEPENDENCY_PACKAGE_NAMES = {
      'bzip2': 'libbz2-dev',
      'fuse': 'libfuse-dev',
      'libcrypto': 'libssl-dev',
      'sqlite': 'libsqlite3-dev',
      'zeromq': 'libzmq3-dev',
      'zlib': 'zlib1g-dev'
  }

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(DPKGBuildHelper, self).__init__(project_definition, l2tdevtools_path)
    self._prep_script = 'prep-dpkg.sh'
    self._post_script = 'post-dpkg.sh'

    self.architecture = None
    self.distribution = None
    self.version_suffix = None

  def _BuildPrepare(
      self, source_directory, project_name, project_version, version_suffix,
      distribution, architecture):
    """Make the necessary preparations before building the dpkg packages.

    Args:
      source_directory (str): name of the source directory.
      project_name (str): name of the project.
      project_version (str): version of the project.
      version_suffix (str): version suffix.
      distribution (str): distribution.
      architecture (str): architecture.

    Returns:
      bool: True if the preparations were successful, False otherwise.
    """
    # Script to run before building, e.g. to change the dpkg packaging files.
    if os.path.exists(self._prep_script):
      command = 'sh ../{0:s} {1:s} {2!s} {3:s} {4:s} {5:s}'.format(
          self._prep_script, project_name, project_version, version_suffix,
          distribution, architecture)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

    return True

  def _BuildFinalize(
      self, source_directory, project_name, project_version, version_suffix,
      distribution, architecture):
    """Make the necessary finalizations after building the dpkg packages.

    Args:
      source_directory (str): name of the source directory.
      project_name (str): name of the project.
      project_version (str): version of the project.
      version_suffix (str): version suffix.
      distribution (str): distribution.
      architecture (str): architecture.

    Returns:
      bool: True if the finalizations were successful, False otherwise.
    """
    # Script to run after building, e.g. to automatically upload the dpkg
    # package files to an apt repository.
    if os.path.exists(self._post_script):
      command = 'sh ../{0:s} {1:s} {2!s} {3:s} {4:s} {5:s}'.format(
          self._post_script, project_name, project_version, version_suffix,
          distribution, architecture)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

    return True

  def _CheckIsInstalled(self, package_name):
    """Checks if a package is installed.

    Args:
      package_name (str): name of the package.

    Returns:
      bool: True if the package is installed, False otherwise.
    """
    command = 'dpkg-query -s {0:s} >/dev/null 2>&1'.format(package_name)
    exit_code = subprocess.call(command, shell=True)
    return exit_code == 0

  def _CreateOriginalSourcePackage(
      self, source_filename, project_name, project_version):
    """Creates the .orig.tar.gz source package.

    Args:
      source_filename (str): name of the source package file.
      project_name (str): project name.
      project_version (str): version of the project.
    """
    if self._project_definition.dpkg_source_name:
      project_name = self._project_definition.dpkg_source_name

    deb_orig_source_filename = '{0:s}_{1!s}.orig.tar.gz'.format(
        project_name, project_version)
    if os.path.exists(deb_orig_source_filename):
      return

    if source_filename.endswith('.zip'):
      self._CreateOriginalSourcePackageFromZip(
          source_filename, deb_orig_source_filename)
    else:
      # TODO: add fix psutil package name.
      shutil.copy(source_filename, deb_orig_source_filename)

  def _CreateOriginalSourcePackageFromZip(
      self, source_filename, orig_source_filename):
    """Creates the .orig.tar.gz source package from a .zip file.

    Args:
      source_filename (str): name of the source package file.
      orig_source_filename (str): name of the .orig.tar.gz source package file.
    """
    with zipfile.ZipFile(source_filename, 'r') as zip_file:
      with tarfile.open(name=orig_source_filename, mode='w:gz') as tar_file:
        for filename in zip_file.namelist():
          with zip_file.open(filename) as file_object:
            tar_info = tarfile.TarInfo(filename)
            tar_file.addfile(tar_info, fileobj=file_object)

  def _CreatePackagingFiles(
      self, source_helper_object, source_directory, project_version):
    """Creates packacking files.

    Args:
      source_helper_object (SourceHelper): source helper.
      source_directory (str): name of the source directory.
      project_version (str): project version.

    Returns:
      bool: True if successful, False otherwise.
    """
    debian_directory = os.path.join(source_directory, 'debian')

    # If there is a debian directory remove it and recreate it from
    # the dpkg directory.
    if os.path.exists(debian_directory):
      logging.info('Removing: {0:s}'.format(debian_directory))
      shutil.rmtree(debian_directory)

    dpkg_directory = os.path.join(source_directory, 'dpkg')

    if not os.path.exists(dpkg_directory):
      dpkg_directory = os.path.join(source_directory, 'config', 'dpkg')

    if os.path.exists(dpkg_directory):
      shutil.copytree(dpkg_directory, debian_directory)

    else:
      os.chdir(source_directory)

      build_files_generator = dpkg_files.DPKGBuildFilesGenerator(
          source_helper_object.project_name, project_version,
          self._project_definition, self._data_path)
      build_files_generator.GenerateFiles('debian')

      os.chdir('..')

    if not os.path.exists(debian_directory):
      logging.error('Missing debian sub directory in: {0:s}'.format(
          source_directory))
      return False

    return True

  def _RemoveOlderDPKGPackages(self, project_name, project_version):
    """Removes previous versions of dpkg packages.

    Args:
      project_name (str): project name.
      project_version (str): project version.
    """
    filenames_to_ignore = '^{0:s}[-_].*{1!s}'.format(
        project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    # Remove files of previous versions in the format:
    # project[-_]*version-[1-9]_architecture.*
    filenames_glob = '{0:s}[-_]*-[1-9]_{1:s}.*'.format(
        project_name, self.architecture)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    # Remove files of previous versions in the format:
    # project[-_]*version-[1-9].*
    filenames_glob = '{0:s}[-_]*-[1-9].*'.format(project_name)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

  def _RemoveOlderOriginalSourcePackage(self, project_name, project_version):
    """Removes previous versions of original source package.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_to_ignore = '^{0:s}_{1!s}.orig.tar.gz'.format(
        project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    # Remove files of previous versions in the format:
    # project_version.orig.tar.gz
    filenames_glob = '{0:s}_*.orig.tar.gz'.format(project_name)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

  def _RemoveOlderSourceDPKGPackages(self, project_name, project_version):
    """Removes previous versions of source dpkg packages.

    Args:
      project_name (str): project name.
      project_version (str): project version.
    """
    filenames_to_ignore = '^{0:s}[-_].*{1!s}'.format(
        project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    # Remove files of previous versions in the format:
    # project[-_]version-[1-9]suffix~distribution_architecture.*
    filenames_glob = '{0:s}[-_]*-[1-9]{1:s}~{2:s}_{3:s}.*'.format(
        project_name, self.version_suffix, self.distribution, self.architecture)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    # Remove files of previous versions in the format:
    # project[-_]*version-[1-9]suffix~distribution.*
    filenames_glob = '{0:s}[-_]*-[1-9]{1:s}~{2:s}.*'.format(
        project_name, self.version_suffix, self.distribution)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    missing_packages = []
    for package_name in self._BUILD_DEPENDENCIES:
      if not self._CheckIsInstalled(package_name):
        missing_packages.append(package_name)

    for package_name in self._project_definition.build_dependencies:
      package_name = self._BUILD_DEPENDENCY_PACKAGE_NAMES.get(
          package_name, [package_name])
      if not self._CheckIsInstalled(package_name):
        missing_packages.append(package_name)

      if package_name not in (
          self._project_definition.dpkg_build_dependencies):
        self._project_definition.dpkg_build_dependencies.append(
            package_name)

    return missing_packages


class ConfigureMakeDPKGBuildHelper(DPKGBuildHelper):
  """Helper to build dpkg packages (.deb)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(ConfigureMakeDPKGBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    self.architecture = platform.machine()
    self.distribution = ''
    self.version_suffix = ''

    if self.architecture == 'i686':
      self.architecture = 'i386'
    elif self.architecture == 'x86_64':
      self.architecture = 'amd64'

  def Build(self, source_helper_object):
    """Builds the dpkg packages.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    project_version = source_helper_object.GetProjectVersion()

    # dpkg-buildpackage wants an source package filename without
    # the status indication and orig indication.
    self._CreateOriginalSourcePackage(
        source_filename, source_helper_object.project_name, project_version)

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building deb of: {0:s}'.format(source_filename))

    if not self._CreatePackagingFiles(
        source_helper_object, source_directory, project_version):
      return False

    # If there is a temporary packaging directory remove it.
    temporary_directory = os.path.join(source_directory, 'tmp')
    if os.path.exists(temporary_directory):
      logging.info('Removing: {0:s}'.format(temporary_directory))
      shutil.rmtree(temporary_directory)

    if not self._BuildPrepare(
        source_directory, source_helper_object.project_name, project_version,
        self.version_suffix, self.distribution, self.architecture):
      return False

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'dpkg-buildpackage -uc -us -rfakeroot > {0:s} 2>&1'.format(
        log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    if not self._BuildFinalize(
        source_directory, source_helper_object.project_name, project_version,
        self.version_suffix, self.distribution, self.architecture):
      return False

    return True

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    deb_filename = '{0:s}_{1!s}-1_{2:s}.deb'.format(
        source_helper_object.project_name, project_version, self.architecture)

    return not os.path.exists(deb_filename)

  def Clean(self, source_helper_object):
    """Cleans the dpkg packages in the current directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    self._RemoveOlderOriginalSourcePackage(
        source_helper_object.project_name, project_version)

    self._RemoveOlderDPKGPackages(
        source_helper_object.project_name, project_version)


class ConfigureMakeSourceDPKGBuildHelper(DPKGBuildHelper):
  """Helper to build source dpkg packages (.deb)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(ConfigureMakeSourceDPKGBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    self._prep_script = 'prep-dpkg-source.sh'
    self._post_script = 'post-dpkg-source.sh'
    self.architecture = 'source'
    self.distribution = 'trusty'
    self.version_suffix = 'ppa1'

  def Build(self, source_helper_object):
    """Builds the dpkg packages.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    project_version = source_helper_object.GetProjectVersion()

    # debuild wants an source package filename without
    # the status indication and orig indication.
    self._CreateOriginalSourcePackage(
        source_filename, source_helper_object.project_name, project_version)

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building source deb of: {0:s}'.format(source_filename))

    if not self._CreatePackagingFiles(
        source_helper_object, source_directory, project_version):
      return False

    # If there is a temporary packaging directory remove it.
    temporary_directory = os.path.join(source_directory, 'tmp')
    if os.path.exists(temporary_directory):
      logging.info('Removing: {0:s}'.format(temporary_directory))
      shutil.rmtree(temporary_directory)

    if not self._BuildPrepare(
        source_directory, source_helper_object.project_name, project_version,
        self.version_suffix, self.distribution, self.architecture):
      return False

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'debuild -S -sa > {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    if not self._BuildFinalize(
        source_directory, source_helper_object.project_name, project_version,
        self.version_suffix, self.distribution, self.architecture):
      return False

    return True

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    changes_filename = '{0:s}_{1!s}-1{2:s}~{3:s}_{4:s}.changes'.format(
        source_helper_object.project_name, project_version,
        self.version_suffix, self.distribution, self.architecture)

    return not os.path.exists(changes_filename)

  def Clean(self, source_helper_object):
    """Cleans the source dpkg packages in the current directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    self._RemoveOlderOriginalSourcePackage(
        source_helper_object.project_name, project_version)

    self._RemoveOlderSourceDPKGPackages(
        source_helper_object.project_name, project_version)


class SetupPyDPKGBuildHelper(DPKGBuildHelper):
  """Helper to build dpkg packages (.deb)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(SetupPyDPKGBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    self.architecture = platform.machine()
    self.distribution = ''
    self.version_suffix = ''

    if not project_definition.architecture_dependent:
      self.architecture = 'all'
    elif self.architecture == 'i686':
      self.architecture = 'i386'
    elif self.architecture == 'x86_64':
      self.architecture = 'amd64'

  def _GetFilenameSafeProjectInformation(self, source_helper_object):
    """Determines the filename safe project name and version.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      tuple: contains:

        * str: filename safe project name.
        * str: version.
    """
    if self._project_definition.dpkg_name:
      project_name = self._project_definition.dpkg_name
    else:
      project_name = source_helper_object.project_name
      if not project_name.startswith('python-'):
        project_name = 'python-{0:s}'.format(project_name)

    project_version = source_helper_object.GetProjectVersion()
    if project_version and project_version.startswith('1!'):
      # Remove setuptools epoch.
      project_version = project_version[2:]

    return project_name, project_version

  def Build(self, source_helper_object):
    """Builds the dpkg packages.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    # dpkg-buildpackage wants an source package filename without
    # the status indication and orig indication.
    self._CreateOriginalSourcePackage(
        source_filename, source_helper_object.project_name, project_version)

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building deb of: {0:s}'.format(source_filename))

    if not self._CreatePackagingFiles(
        source_helper_object, source_directory, project_version):
      return False

    # If there is a temporary packaging directory remove it.
    temporary_directory = os.path.join(source_directory, 'tmp')
    if os.path.exists(temporary_directory):
      logging.info('Removing: {0:s}'.format(temporary_directory))
      shutil.rmtree(temporary_directory)

    if not self._BuildPrepare(
        source_directory, project_name, project_version, self.version_suffix,
        self.distribution, self.architecture):
      return False

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'dpkg-buildpackage -uc -us -rfakeroot > {0:s} 2>&1'.format(
        log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    if not self._BuildFinalize(
        source_directory, project_name, project_version, self.version_suffix,
        self.distribution, self.architecture):
      return False

    return True

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    deb_filename = '{0:s}_{1!s}-1_{2:s}.deb'.format(
        project_name, project_version, self.architecture)

    return not os.path.exists(deb_filename)

  def Clean(self, source_helper_object):
    """Cleans the dpkg packages in the current directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._RemoveOlderOriginalSourcePackage(
        source_helper_object.project_name, project_version)

    self._RemoveOlderDPKGPackages(project_name, project_version)

    if not self._IsPython2Only():
      project_name = 'python3-{0:s}'.format(project_name[7])

      self._RemoveOlderDPKGPackages(project_name, project_version)


class SetupPySourceDPKGBuildHelper(DPKGBuildHelper):
  """Helper to build source dpkg packages (.deb)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(SetupPySourceDPKGBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    self._prep_script = 'prep-dpkg-source.sh'
    self._post_script = 'post-dpkg-source.sh'
    self.architecture = 'source'
    self.distribution = 'trusty'
    self.version_suffix = 'ppa1'

  def _GetFilenameSafeProjectInformation(self, source_helper_object):
    """Determines the filename safe project name and version.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      tuple: contains:

        * str: filename safe project name.
        * str: version.
    """
    if self._project_definition.dpkg_source_name:
      project_name = self._project_definition.dpkg_source_name
    else:
      project_name = source_helper_object.project_name
      if not project_name.startswith('python-'):
        project_name = 'python-{0:s}'.format(project_name)

    project_version = source_helper_object.GetProjectVersion()
    if project_version and project_version.startswith('1!'):
      # Remove setuptools epoch.
      project_version = project_version[2:]

    return project_name, project_version

  def Build(self, source_helper_object):
    """Builds the dpkg packages.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    # debuild wants an source package filename without
    # the status indication and orig indication.
    self._CreateOriginalSourcePackage(
        source_filename, source_helper_object.project_name, project_version)

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building source deb of: {0:s}'.format(source_filename))

    if not self._CreatePackagingFiles(
        source_helper_object, source_directory, project_version):
      return False

    # If there is a temporary packaging directory remove it.
    temporary_directory = os.path.join(source_directory, 'tmp')
    if os.path.exists(temporary_directory):
      logging.info('Removing: {0:s}'.format(temporary_directory))
      shutil.rmtree(temporary_directory)

    if not self._BuildPrepare(
        source_directory, project_name, project_version, self.version_suffix,
        self.distribution, self.architecture):
      return False

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'debuild -S -sa > {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    if not self._BuildFinalize(
        source_directory, project_name, project_version, self.version_suffix,
        self.distribution, self.architecture):
      return False

    return True

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    changes_filename = '{0:s}_{1!s}-1{2:s}~{3:s}_{4:s}.changes'.format(
        project_name, project_version, self.version_suffix, self.distribution,
        self.architecture)

    return not os.path.exists(changes_filename)

  def Clean(self, source_helper_object):
    """Cleans the dpkg packages in the current directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    self._RemoveOlderOriginalSourcePackage(
        source_helper_object.project_name, project_version)

    self._RemoveOlderSourceDPKGPackages(
        source_helper_object.project_name, project_version)


class MSIBuildHelper(BuildHelper):
  """Helper to build Microsoft Installer packages (.msi)."""

  _COMMON_PATCH_EXE_PATHS = [
      '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join('GnuWin', 'bin', 'patch.exe')),
      '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join('GnuWin32', 'bin', 'patch.exe')),
      '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join(
              'Program Files (x86)', 'GnuWin', 'bin', 'patch.exe')),
      '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join(
              'Program Files (x86)', 'GnuWin32', 'bin', 'patch.exe')),
      '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join(
              'ProgramData', 'chocolatey', 'bin', 'patch.exe'))
  ]

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(MSIBuildHelper, self).__init__(project_definition, l2tdevtools_path)
    self.architecture = platform.machine()

    if self.architecture == 'x86':
      self.architecture = 'win32'
    elif self.architecture == 'AMD64':
      self.architecture = 'win-amd64'

  def _ApplyPatches(self, patches):
    """Applies patches.

    Args:
      source_directory (str): name of the source directory.
      patches (list[str]): patch file names.

    Returns:
      bool: True if applying the patches was successful.
    """
    # Search common locations for patch.exe
    patch_exe_path = None
    for patch_exe_path in self._COMMON_PATCH_EXE_PATHS:
      if os.path.exists(patch_exe_path):
        break

    if not patch_exe_path:
      logging.error('Unable to find patch.exe')
      return False

    for patch_filename in patches:
      filename = os.path.join(self._data_path, 'patches', patch_filename)
      if not os.path.exists(filename):
        logging.warning('Missing patch file: {0:s}'.format(filename))
        continue

      command = '\"{0:s}\" --force --binary --input {1:s}'.format(
          patch_exe_path, filename)
      exit_code = subprocess.call(command, shell=False)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

    return True

  def _RunPreBuildScript(self, script):
    """Runs the msi_prebuild script.

    Args:
      script (str): the script's filename.

    Returns:
      bool: True if running the script was successful.
    """
    filepath = os.path.join(self._data_path, 'msi_prebuild', script)
    if filepath.endswith('.ps1'):
      command = 'powershell.exe "{0:s}"'.format(filepath)

    elif filepath.endswith('py'):
      command = '{0:s} "{1:s}"'.format(sys.executable, filepath)

    exit_code = subprocess.call(command, shell=False)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True


class ConfigureMakeMSIBuildHelper(MSIBuildHelper):
  """Helper to build Microsoft Installer packages (.msi)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.

    Raises:
      RuntimeError: if the Visual Studio version could be determined or
                    msvscpp-convert.py could not be found.
    """
    super(ConfigureMakeMSIBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)

    if 'VS150COMNTOOLS' in os.environ:
      self.version = '2017'

    elif 'VS140COMNTOOLS' in os.environ:
      self.version = '2015'

    elif 'VS120COMNTOOLS' in os.environ:
      self.version = '2013'

    elif 'VS110COMNTOOLS' in os.environ:
      self.version = '2012'

    elif 'VS100COMNTOOLS' in os.environ:
      self.version = '2010'

    # Since the script exports VS90COMNTOOLS to the environment we need
    # to check the other Visual Studio environment variables first.
    elif 'VS90COMNTOOLS' in os.environ:
      self.version = '2008'

    elif 'VCINSTALLDIR' in os.environ:
      self.version = 'python'

    else:
      raise RuntimeError('Unable to determine Visual Studio version.')

    if self.version != '2008':
      self._msvscpp_convert = os.path.join(
          l2tdevtools_path, 'tools', 'msvscpp-convert.py')

      if not os.path.exists(self._msvscpp_convert):
        raise RuntimeError('Unable to find msvscpp-convert.py')

  def _BuildMSBuild(self, source_helper_object, source_directory):
    """Builds using Visual Studio and MSBuild.

    Args:
      source_helper_object (SourceHelper): source helper.
      source_directory (str): name of the source directory.

    Returns:
      bool: True if successful, False otherwise.
    """
    # Search common locations for MSBuild.exe
    if self.version == '2008':
      msbuild = '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join(
              'Windows', 'Microsoft.NET', 'Framework', 'v3.5',
              'MSBuild.exe'))

    # Note that MSBuild in .NET 3.5 does not support vs2010 solution files
    # and MSBuild in .NET 4.0 is needed instead.
    elif self.version in ('2010', '2012', '2013', '2015', '2017'):
      msbuild = '{0:s}:{1:s}{2:s}'.format(
          'C', os.sep, os.path.join(
              'Windows', 'Microsoft.NET', 'Framework', 'v4.0.30319',
              'MSBuild.exe'))

    else:
      msbuild = ''

    if not msbuild or not os.path.exists(msbuild):
      logging.error('Unable to find MSBuild.exe')
      return False

    if self.version == '2008':
      if not os.environ['VS90COMNTOOLS']:
        logging.error('Missing VS90COMNTOOLS environment variable.')
        return False

    elif self.version == '2010':
      if not os.environ['VS100COMNTOOLS']:
        logging.error('Missing VS100COMNTOOLS environment variable.')
        return False

    elif self.version == '2012':
      if not os.environ['VS110COMNTOOLS']:
        logging.error('Missing VS110COMNTOOLS environment variable.')
        return False

    elif self.version == '2013':
      if not os.environ['VS120COMNTOOLS']:
        logging.error('Missing VS120COMNTOOLS environment variable.')
        return False

    elif self.version == '2015':
      if not os.environ['VS140COMNTOOLS']:
        logging.error('Missing VS140COMNTOOLS environment variable.')
        return False

    elif self.version == '2017':
      if not os.environ['VS150COMNTOOLS']:
        logging.error('Missing VS150COMNTOOLS environment variable.')
        return False

    elif self.version == 'python':
      if not os.environ['VCINSTALLDIR']:
        logging.error('Missing VCINSTALLDIR environment variable.')
        return False

    zlib_project_file = os.path.join(
        source_directory, 'msvscpp', 'zlib', 'zlib.vcproj')
    zlib_source_directory = os.path.join(
        os.path.dirname(source_directory), 'zlib')

    if (os.path.exists(zlib_project_file) and
        not os.path.exists(zlib_source_directory)):
      logging.error('Missing dependency: zlib.')
      return False

    dokan_project_file = os.path.join(
        source_directory, 'msvscpp', 'dokan', 'dokan.vcproj')
    dokan_source_directory = os.path.join(
        os.path.dirname(source_directory), 'dokan')

    if (os.path.exists(dokan_project_file) and
        not os.path.exists(dokan_source_directory)):
      logging.error('Missing dependency: dokan.')
      return False

    # For the Visual Studio builds later than 2008 the convert the 2008
    # solution and project files need to be converted to the newer version.
    if self.version in ('2010', '2012', '2013', '2015', '2017'):
      self._ConvertSolutionFiles(source_directory)

    # Detect architecture based on Visual Studion Platform environment
    self._BuildPrepare(source_helper_object, source_directory)

    # variable. If not set the platform with default to Win32.
    msvscpp_platform = os.environ.get('Platform', None)
    if not msvscpp_platform:
      msvscpp_platform = os.environ.get('TARGET_CPU', None)

    if not msvscpp_platform or msvscpp_platform == 'x86':
      msvscpp_platform = 'Win32'

    if msvscpp_platform not in ('Win32', 'x64'):
      logging.error('Unsupported build platform: {0:s}'.format(
          msvscpp_platform))
      return False

    if self.version == '2008' and msvscpp_platform == 'x64':
      logging.error('Unsupported 64-build platform for vs2008.')
      return False

    filenames_glob = os.path.join(source_directory, 'msvscpp', '*.sln')
    solution_filenames = glob.glob(filenames_glob)

    if len(solution_filenames) != 1:
      logging.error('Unable to find Visual Studio solution file')
      return False

    solution_filename = solution_filenames[0]

    command = (
        '\"{0:s}\" /p:Configuration=Release /p:Platform={1:s} '
        '/noconsolelogger /fileLogger /maxcpucount {2:s}').format(
            msbuild, msvscpp_platform, solution_filename)
    exit_code = subprocess.call(command, shell=False)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    python_module_name, _, _ = source_directory.partition('-')
    python_module_name = 'py{0:s}'.format(python_module_name[3:])
    python_module_directory = os.path.join(
        source_directory, python_module_name)
    python_module_dist_directory = os.path.join(
        python_module_directory, 'dist')

    if os.path.exists(python_module_dist_directory):
      return True

    build_directory = os.path.join('..', '..')

    os.chdir(python_module_directory)

    result = self._BuildSetupPy()
    if result:
      result = self._MoveMSI(python_module_name, build_directory)

    os.chdir(build_directory)

    return result

  def _BuildPrepare(self, source_helper_object, source_directory):
    """Prepares the source for building with Visual Studio.

    Args:
      source_helper_object (SourceHelper): source helper.
      source_directory (str): name of the source directory.
    """
    # For the vs2008 build make sure the binary is XP compatible,
    # by setting WINVER to 0x0501. For the vs2010 build WINVER is
    # set to 0x0600 (Windows Vista).

    # WINVER is set in common\config_winapi.h or common\config_msc.h.
    config_filename = os.path.join(
        source_directory, 'common', 'config_winapi.h')

    # If the WINAPI configuration file is not available use
    # the MSC compiler configuration file instead.
    if not os.path.exists(config_filename):
      config_filename = os.path.join(
          source_directory, 'common', 'config_msc.h')

    # Add a line to the config file that sets WINVER.
    parsing_mode = 0

    for line in fileinput.input(config_filename, inplace=1):
      # Remove trailing whitespace and end-of-line characters.
      line = line.rstrip()

      if parsing_mode != 2 or line:
        if parsing_mode == 1:
          # TODO: currently we want libbde not use Windows Crypto API, hence
          # we set WINVER to 0x0501.
          if (self.version == '2008' or
              source_helper_object.project_name == 'libbde'):
            if not line.startswith(b'#define WINVER 0x0501'):
              print(b'#define WINVER 0x0501')
              print(b'')

          else:
            if not line.startswith(b'#define WINVER 0x0600'):
              print(b'#define WINVER 0x0600')
              print(b'')

          parsing_mode = 2

        elif line.startswith(b'#define _CONFIG_'):
          parsing_mode = 1

      print(line)

  def _BuildSetupPy(self):
    """Builds using Visual Studio and setup.py.

    This function assumes setup.py is present in the current working
    directory.

    Returns:
      bool: True if successful, False otherwise.
    """
    # Setup.py uses VS90COMNTOOLS which is vs2008 specific
    # so we need to set it for the other Visual Studio versions.
    if self.version == '2010':
      os.environ['VS90COMNTOOLS'] = os.environ['VS100COMNTOOLS']

    elif self.version == '2012':
      os.environ['VS90COMNTOOLS'] = os.environ['VS110COMNTOOLS']

    elif self.version == '2013':
      os.environ['VS90COMNTOOLS'] = os.environ['VS120COMNTOOLS']

    elif self.version == '2015':
      os.environ['VS90COMNTOOLS'] = os.environ['VS140COMNTOOLS']

    elif self.version == '2017':
      os.environ['VS90COMNTOOLS'] = os.environ['VS150COMNTOOLS']

    elif self.version == 'python':
      os.environ['VS90COMNTOOLS'] = os.environ['VCINSTALLDIR']

    command = '\"{0:s}\" setup.py bdist_msi'.format(sys.executable)
    exit_code = subprocess.call(command, shell=False)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _ConvertSolutionFiles(self, source_directory):
    """Converts the Visual Studio solution and project files.

    Args:
      source_directory (str): name of the source directory.
    """
    logging.info('Converting Visual Studio solution and project files.')
    os.chdir(source_directory)

    filenames_glob = os.path.join('msvscpp', '*.sln')
    solution_filenames = glob.glob(filenames_glob)

    if len(solution_filenames) != 1:
      logging.error('Unable to find Visual Studio solution file')
      return False

    solution_filename = solution_filenames[0]

    if not os.path.exists('vs2008'):
      command = '\"{0:s}\" {1:s} --to {2:s} {3:s}'.format(
          sys.executable, self._msvscpp_convert, self.version,
          solution_filename)
      exit_code = subprocess.call(command, shell=False)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      # Note that setup.py needs the Visual Studio solution directory
      # to be named: msvscpp. So replace the Visual Studio 2008 msvscpp
      # solution directory with the converted one.
      os.rename('msvscpp', 'vs2008')
      os.rename('vs{0:s}'.format(self.version), 'msvscpp')

    os.chdir('..')

  def _MoveMSI(self, python_module_name, build_directory):
    """Moves the MSI from the dist sub directory into the build directory.

    Args:
      python_module_name (str): Python module name.
      build_directory (str): build directory.

    Returns:
      bool: True if the move was successful, False otherwise.
    """
    filenames_glob = os.path.join(
        'dist', '{0:s}-*.msi'.format(python_module_name))
    filenames = glob.glob(filenames_glob)

    if len(filenames) != 1:
      logging.error('Unable to find MSI file: {0:s}.'.format(filenames_glob))
      return False

    _, _, msi_filename = filenames[0].rpartition(os.path.sep)
    msi_filename = os.path.join(build_directory, msi_filename)
    if os.path.exists(msi_filename):
      logging.warning('MSI file already exists.')
    else:
      logging.info('Moving: {0:s}'.format(filenames[0]))
      shutil.move(filenames[0], build_directory)

    return True

  def _SetupBuildDependencyDokan(self):
    """Sets up the dokan build dependency.

    Returns:
      bool: True if successful, False otherwise.
    """
    # TODO: implement.
    return False

  def _SetupBuildDependencyZeroMQ(self):
    """Sets up the zeromq build dependency.

    Returns:
      bool: True if successful, False otherwise.
    """
    # TODO: implement.
    return False

  def _SetupBuildDependencyZlib(self):
    """Sets up the zlib build dependency.

    Returns:
      bool: True if successful, False otherwise.
    """
    download_helper_object = download_helper.ZlibDownloadHelper(
        'http://www.zlib.net')
    source_helper_object = source_helper.SourcePackageHelper(
        'zlib', None, download_helper_object)

    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(
              source_filename))
      return False

    if not os.path.exists('zlib'):
      os.rename(source_directory, 'zlib')

    return True

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    missing_packages = []
    for package_name in self._project_definition.build_dependencies:
      if package_name == 'fuse':
        self._SetupBuildDependencyDokan()

      elif package_name == 'zeromq':
        self._SetupBuildDependencyZeroMQ()

      elif package_name == 'zlib':
        self._SetupBuildDependencyZlib()

      elif package_name != 'libcrypto':
        missing_packages.append(package_name)

    return missing_packages

  def Build(self, source_helper_object):
    """Builds using Visual Studio.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building: {0:s} with Visual Studio {1:s}'.format(
        source_filename, self.version))

    if self._project_definition.patches:
      os.chdir(source_directory)
      result = self._ApplyPatches(self._project_definition.patches)
      os.chdir('..')

      if not result:
        return False

    result = False

    setup_py_path = os.path.join(source_directory, 'setup.py')
    if not os.path.exists(setup_py_path):
      result = self._BuildMSBuild(source_helper_object, source_directory)

    else:
      python_module_name, _, _ = source_directory.partition('-')
      python_module_dist_directory = os.path.join(source_directory, 'dist')

      if not os.path.exists(python_module_dist_directory):
        build_directory = os.path.join('..')

        os.chdir(source_directory)

        result = self._BuildSetupPy()
        if result:
          result = self._MoveMSI(python_module_name, build_directory)

        os.chdir(build_directory)

    return result

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    msi_filename = '{0:s}-python-{1!s}.1.{2:s}-py2.7.msi'.format(
        source_helper_object.project_name, project_version, self.architecture)

    return not os.path.exists(msi_filename)

  def Clean(self, source_helper_object):
    """Cleans the build and dist directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    # Remove previous versions of MSIs.
    filenames_to_ignore = 'py{0:s}-.*{1!s}.1.{2:s}-py2.7.msi'.format(
        source_helper_object.project_name[3:], project_version,
        self.architecture)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    filenames_glob = 'py{0:s}-*.1.{1:s}-py2.7.msi'.format(
        source_helper_object.project_name[3:], self.architecture)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    filenames_to_ignore = '{0:s}-python-.*{1!s}.1.{2:s}-py2.7.msi'.format(
        source_helper_object.project_name, project_version, self.architecture)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    filenames_glob = '{0:s}-python-*.1.{1:s}-py2.7.msi'.format(
        source_helper_object.project_name, self.architecture)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)


class SetupPyMSIBuildHelper(MSIBuildHelper):
  """Helper to build Microsoft Installer packages (.msi)."""

  def _GetFilenameSafeProjectInformation(self, source_helper_object):
    """Determines the filename safe project name and version.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      tuple: contains:

        * str: filename safe project name.
        * str: version.
    """
    if self._project_definition.setup_name:
      project_name = self._project_definition.setup_name
    else:
      project_name = source_helper_object.project_name

    project_version = source_helper_object.GetProjectVersion()

    if source_helper_object.project_name == 'dfvfs':
      project_version = '{0!s}.1'.format(project_version)
    else:
      project_version = '{0!s}'.format(project_version)

    return project_name, project_version

  def Build(self, source_helper_object):
    """Builds the msi.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building msi of: {0:s}'.format(source_filename))

    if self._project_definition.patches:
      os.chdir(source_directory)
      result = self._ApplyPatches(self._project_definition.patches)
      os.chdir('..')

      if not result:
        return False

    if self._project_definition.msi_prebuild:
      os.chdir(source_directory)
      result = self._RunPreBuildScript(self._project_definition.msi_prebuild)
      os.chdir('..')

      if not result:
        return False

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = '\"{0:s}\" setup.py bdist_msi > {1:s} 2>&1'.format(
        sys.executable, log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    # Move the msi to the build directory.
    project_name, _ = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    filenames_glob = os.path.join(
        source_directory, 'dist', '{0:s}-*.msi'.format(project_name))
    filenames = glob.glob(filenames_glob)

    if len(filenames) != 1:
      logging.error('Unable to find MSI file: {0:s}.'.format(filenames_glob))
      return False

    _, _, msi_filename = filenames[0].rpartition(os.path.sep)
    if os.path.exists(msi_filename):
      logging.warning('MSI file already exists.')
    else:
      logging.info('Moving: {0:s}'.format(filenames[0]))
      shutil.move(filenames[0], '.')

    return True

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    missing_packages = []
    for package_name in self._project_definition.build_dependencies:
      # Ignore sqlite dependency for MSI builds
      if package_name != 'sqlite':
        missing_packages.append(package_name)
    return missing_packages

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    # TODO: it looks like coverage is no architecture dependent on Windows.
    # Check if it is architecture dependent on other platforms.
    if (self._project_definition.architecture_dependent and
        project_name != 'coverage'):
      suffix = '-py2.7'
    else:
      suffix = ''

    # MSI does not support a single number version therefore we add '.1'.
    if '.' not in project_version:
      project_version = '{0!s}.1'.format(project_version)

    # MSI does not support a 4 digit version, e.g. '1.2.3.4' therefore
    # we remove the last digit.
    elif len(project_version.split('.')) == 4:
      project_version, _, _ = project_version.rpartition('.')

    # MSI does not support a version containing a '-', e.g. '1.2.3-4'
    # therefore we remove the digit after the '-'.
    elif '-' in project_version:
      project_version, _, _ = project_version.rpartition('-')

    msi_filename = '{0:s}-{1:s}.{2:s}{3:s}.msi'.format(
        project_name, project_version, self.architecture, suffix)

    return not os.path.exists(msi_filename)

  def Clean(self, source_helper_object):
    """Cleans the build and dist directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    # Remove previous versions build directories.
    for filename in ('build', 'dist'):
      if os.path.exists(filename):
        logging.info('Removing: {0:s}'.format(filename))
        shutil.rmtree(filename, True)

    # Remove previous versions of MSIs.
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    if self._project_definition.architecture_dependent:
      suffix = '-py2.7'
    else:
      suffix = ''

    # MSI does not support a single number version therefore we add '.1'.
    if '.' not in project_version:
      project_version = '{0!s}.1'.format(project_version)

    # MSI does not support a 4 digit version, e.g. '1.2.3.4' there we remove
    # the last digit.
    elif len(project_version.split('.')) == 4:
      project_version, _, _ = project_version.rpartition('.')

    # MSI does not support a version containing a '-', e.g. '1.2.3-4' there
    # we remove the digit after the '-'.
    elif '-' in project_version:
      project_version, _, _ = project_version.rpartition('-')

    filenames_to_ignore = '{0:s}-.*{1!s}.{2:s}{3:s}.msi'.format(
        project_name, project_version, self.architecture, suffix)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    filenames_glob = '{0:s}-*.{1:s}{2:s}.msi'.format(
        project_name, self.architecture, suffix)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)


class OSCBuildHelper(BuildHelper):
  """Helper to build with osc for the openSUSE build service."""

  _OSC_PROJECT = 'home:joachimmetz:testing'

  _OSC_PACKAGE_METADATA = (
      '<package name="{name:s}" project="{project:s}">\n'
      '  <title>{title:s}</title>\n'
      '  <description>{description:s}</description>\n'
      '</package>\n')

  def _BuildPrepare(self, source_helper_object):
    """Prepares the source for building with osc.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    # Checkout the project if it does not exist otherwise make sure
    # the project files are up to date.
    if not os.path.exists(self._OSC_PROJECT):
      if not self._OSCCheckout():
        return

    else:
      if not self._OSCUpdate():
        return False

    # Create a package of the project if it does not exist.
    osc_package_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name)
    if os.path.exists(osc_package_path):
      return True

    if not self._OSCCreatePackage(source_helper_object):
      return False

    if not self._OSCUpdate():
      return False

    return True

  def _CheckStatusIsClean(self):
    """Runs osc status to check if the status is clean.

    Returns:
      bool: True if successful, False otherwise.
    """
    command = 'osc status {0:s}'.format(self._OSC_PROJECT)
    arguments = shlex.split(command)
    process = subprocess.Popen(
        arguments, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    if not process:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    output, error = process.communicate()
    if process.returncode != 0:
      logging.error('Running: "{0:s}" failed with error: {1!s}.'.format(
          command, error))
      return False

    if output:
      logging.error('Unable to continue with pending changes.')
      return False

    return True

  def _OSCAdd(self, path):
    """Runs osc add to add a new file.

    Args:
      path (str): path of the file to add, relative to the osc project
          directory.

    Returns:
      bool: True if successful, False otherwise.
    """
    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'osc -q add {0:s} >> {1:s} 2>&1'.format(path, log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        self._OSC_PROJECT, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _OSCCheckout(self):
    """Runs osc checkout.

    Returns:
      bool: True if successful, False otherwise.
    """
    command = 'osc -q checkout {0:s} >> {1:s} 2>&1 '.format(
        self._OSC_PROJECT, self.LOG_FILENAME)
    exit_code = subprocess.call(command, shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _OSCCommit(self, package_name):
    """Runs osc commit.

    Args:
      package_name (str): name of the package.

    Returns:
      bool: True if successful, False otherwise.
    """
    # Running osc commit from the package sub directory is more efficient.
    osc_project_path = os.path.join(self._OSC_PROJECT, package_name)
    log_file_path = os.path.join('..', '..', self.LOG_FILENAME)
    command = 'osc -q commit -n >> {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        osc_project_path, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _OSCCreatePackage(self, source_helper_object):
    """Runs osc meta pkg to create a new package.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    template_values = {
        'description': source_helper_object.project_name,
        'name': source_helper_object.project_name,
        'project': self._OSC_PROJECT,
        'title': source_helper_object.project_name}

    package_metadata = self._OSC_PACKAGE_METADATA.format(**template_values)

    command = (
        'osc -q meta pkg -F - {0:s} {1:s} << EOI\n{2:s}\nEOI\n').format(
            self._OSC_PROJECT, source_helper_object.project_name,
            package_metadata)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        self._OSC_PROJECT, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _OSCUpdate(self):
    """Runs osc update.

    Returns:
      bool: True if successful, False otherwise.
    """
    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = 'osc -q update >> {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        self._OSC_PROJECT, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    # Dependencies are handled by the openSUSE build service.
    return []

  def Clean(self, source_helper_object):
    """Cleans the build and dist directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    osc_package_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name)
    osc_source_filename = '{0:s}-{1!s}.tar.gz'.format(
        source_helper_object.project_name, project_version)

    filenames_to_ignore = '^{0:s}'.format(
        os.path.join(osc_package_path, osc_source_filename))
    filenames_to_ignore = re.compile(filenames_to_ignore)

    # Remove files of previous versions in the format:
    # project-version.tar.gz
    osc_source_filename_glob = '{0:s}-*.tar.gz'.format(
        source_helper_object.project_name)
    filenames_glob = os.path.join(osc_package_path, osc_source_filename_glob)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))

        command = 'osc -q remove {0:s}'.format(os.path.basename(filename))
        exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
            osc_package_path, command), shell=True)
        if exit_code != 0:
          logging.error('Running: "{0:s}" failed.'.format(command))


class ConfigureMakeOSCBuildHelper(OSCBuildHelper):
  """Helper to build with osc for the openSUSE build service."""

  def Build(self, source_helper_object):
    """Builds the osc package.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    project_version = source_helper_object.GetProjectVersion()

    logging.info('Preparing osc build of: {0:s}'.format(source_filename))

    if not self._BuildPrepare(source_helper_object):
      return False

    osc_package_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name)

    # osc wants the project filename without the status indication.
    osc_source_filename = '{0:s}-{1!s}.tar.gz'.format(
        source_helper_object.project_name, project_version)

    # Copy the source package to the package directory.
    osc_source_path = os.path.join(osc_package_path, osc_source_filename)
    shutil.copy(source_filename, osc_source_path)

    osc_source_path = os.path.join(
        source_helper_object.project_name, osc_source_filename)
    if not self._OSCAdd(osc_source_path):
      return False

    # Extract the build files from the source package into the package
    # directory.
    spec_filename = '{0:s}.spec'.format(source_helper_object.project_name)

    osc_spec_file_path = os.path.join(osc_package_path, spec_filename)
    spec_file_exists = os.path.exists(osc_spec_file_path)

    command = 'tar xfO {0:s} {1:s}-{2!s}/{3:s} > {3:s}'.format(
        osc_source_filename, source_helper_object.project_name,
        project_version, spec_filename)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        osc_package_path, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    if not spec_file_exists:
      osc_spec_file_path = os.path.join(
          source_helper_object.project_name, spec_filename)
      if not self._OSCAdd(osc_spec_file_path):
        return False

    return self._OSCCommit(source_helper_object.project_name)

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    osc_source_filename = '{0:s}-{1!s}.tar.gz'.format(
        source_helper_object.project_name, project_version)

    osc_source_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name,
        osc_source_filename)

    return not os.path.exists(osc_source_path)


class SetupPyOSCBuildHelper(OSCBuildHelper):
  """Helper to build with osc for the openSUSE build service."""

  _DOC_FILENAMES = [
      'CHANGES', 'CHANGES.txt', 'CHANGES.TXT',
      'README', 'README.txt', 'README.TXT']

  _LICENSE_FILENAMES = [
      'LICENSE', 'LICENSE.txt', 'LICENSE.TXT']

  def _GetSetupPySpecFilePath(self, source_helper_object, source_directory):
    """Retrieves the path of the setup.py generated .spec file.

    Args:
      source_helper_object (SourceHelper): source helper.
      source_directory (str): name of the source directory.

    Returns:
      str: path of the setup.py generated .spec file.
    """
    if self._project_definition.setup_name:
      setup_name = self._project_definition.setup_name
    else:
      setup_name = source_helper_object.project_name

    spec_filename = '{0:s}.spec'.format(setup_name)

    return os.path.join(source_directory, 'dist', spec_filename)

  def Build(self, source_helper_object):
    """Builds the osc package.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    logging.info('Preparing osc build of: {0:s}'.format(source_filename))

    if not self._BuildPrepare(source_helper_object):
      return False

    osc_package_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name)

    osc_source_path = os.path.join(osc_package_path, source_filename)
    if not os.path.exists(osc_source_path):
      # Copy the source package to the package directory if needed.
      shutil.copy(source_filename, osc_source_path)

      osc_source_path = os.path.join(
          source_helper_object.project_name, source_filename)
      if not self._OSCAdd(osc_source_path):
        return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    spec_file_generator = spec_file.RPMSpecFileGenerator(self._data_path)

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    if not spec_file_generator.GenerateWithSetupPy(
        source_directory, log_file_path):
      return False

    project_name = source_helper_object.project_name
    if project_name.startswith('python-') and project_name != 'python-gflags':
      project_name = project_name[7:]

    # TODO: determine project version.
    project_version = ''

    input_file_path = self._GetSetupPySpecFilePath(
        source_helper_object, source_directory)

    spec_filename = '{0:s}.spec'.format(project_name)
    output_file_path = os.path.join(osc_package_path, spec_filename)

    # Determine if the output file exists before it is generated.
    output_file_exists = os.path.exists(output_file_path)

    if not spec_file_generator.RewriteSetupPyGeneratedFileForOSC(
        self._project_definition, source_directory, source_filename,
        project_name, project_version, input_file_path, output_file_path):
      return False

    if not output_file_exists:
      output_file_path = os.path.join(
          source_helper_object.project_name, spec_filename)
      if not self._OSCAdd(output_file_path):
        return False

    return self._OSCCommit(source_helper_object.project_name)

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    osc_source_filename = '{0:s}-{1!s}.tar.gz'.format(
        source_helper_object.project_name, project_version)

    osc_source_path = os.path.join(
        self._OSC_PROJECT, source_helper_object.project_name,
        osc_source_filename)

    return not os.path.exists(osc_source_path)


class PKGBuildHelper(BuildHelper):
  """Helper to build MacOS-X packages (.pkg)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(PKGBuildHelper, self).__init__(project_definition, l2tdevtools_path)
    self._pkgbuild = os.path.join('/', 'usr', 'bin', 'pkgbuild')

  def _BuildDmg(self, pkg_filename, dmg_filename):
    """Builds the distributable disk image (.dmg) from the pkg.

    Args:
      pkg_filename (str): name of the pkg file (which is technically
          a directory).
      dmg_filename (str): name of the dmg file.

    Returns:
      bool: True if successful, False otherwise.
    """
    command = (
        'hdiutil create {0:s} -srcfolder {1:s} -fs HFS+').format(
            dmg_filename, pkg_filename)
    exit_code = subprocess.call(command, shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _BuildPKG(
      self, source_directory, project_identifier, project_version,
      pkg_filename):
    """Builds the distributable disk image (.dmg) from the pkg.

    Args:
      source_directory (str): name of the source directory.
      project_identifier (str): project identifier.
      project_version (str): version of the project.
      pkg_filename (str): name of the pkg file (which is technically
          a directory).

    Returns:
      bool: True if successful, False otherwise.
    """
    command = (
        '{0:s} --root {1:s}/tmp/ --identifier {2:s} '
        '--version {3!s} --ownership recommended {4:s}').format(
            self._pkgbuild, source_directory, project_identifier,
            project_version, pkg_filename)
    exit_code = subprocess.call(command, shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    # TODO: implement build dependency check.
    return []

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_version = source_helper_object.GetProjectVersion()

    dmg_filename = '{0:s}-{1!s}.dmg'.format(
        source_helper_object.project_name, project_version)

    return not os.path.exists(dmg_filename)

  def Clean(self, source_helper_object):
    """Cleans the MacOS-X packages in the current directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_version = source_helper_object.GetProjectVersion()

    filenames_to_ignore = '^{0:s}-.*{1!s}'.format(
        source_helper_object.project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    # Remove files of previous versions in the format:
    # project-*version.dmg
    filenames_glob = '{0:s}-*.dmg'.format(source_helper_object.project_name)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    # Remove files of previous versions in the format:
    # project-*version.pkg
    filenames_glob = '{0:s}-*.pkg'.format(source_helper_object.project_name)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)


class ConfigureMakePKGBuildHelper(PKGBuildHelper):
  """Helper to build MacOS-X packages (.pkg)."""

  _DOC_FILENAMES = frozenset([
      'AUTHORS',
      'AUTHORS.txt',
      'COPYING',
      'COPYING.txt',
      'LICENSE',
      'LICENSE.txt',
      'NEWS',
      'NEWS.txt',
      'README',
      'README.md',
      'README.txt'])

  _SDK_VERSIONS = ('10.7', '10.8', '10.9', '10.10', '10.11', '10.12')

  def Build(self, source_helper_object):
    """Builds the pkg package and distributable disk image (.dmg).

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    project_version = source_helper_object.GetProjectVersion()

    logging.info('Building pkg of: {0:s}'.format(source_filename))

    if self._project_definition.patches:
      # TODO: add self._ApplyPatches
      pass

    dmg_filename = '{0:s}-{1!s}.dmg'.format(
        source_helper_object.project_name, project_version)
    pkg_filename = '{0:s}-{1!s}.pkg'.format(
        source_helper_object.project_name, project_version)
    log_file_path = os.path.join('..', self.LOG_FILENAME)

    sdks_path = os.path.join(
        '/', 'Applications', 'Xcode.app', 'Contents', 'Developer',
        'Platforms', 'MacOSX.platform', 'Developer', 'SDKs')

    sdk_path = None
    for sdk_version in self._SDK_VERSIONS:
      sdk_sub_path = 'MacOSX{0:s}.sdk'.format(sdk_version)
      if os.path.isdir(sdk_sub_path):
        sdk_path = os.path.join(sdks_path, sdk_sub_path)
        break

    if sdk_path:
      cflags = 'CFLAGS="-isysroot {0:s}"'.format(sdk_path)
      ldflags = 'LDFLAGS="-Wl,-syslibroot,{0:s}"'.format(sdk_path)
    else:
      cflags = ''
      ldflags = ''

    if not os.path.exists(pkg_filename):
      prefix = '/usr/local'
      configure_options = ''
      if self._project_definition.pkg_configure_options:
        configure_options = ' '.join(
            self._project_definition.pkg_configure_options)

      elif self._project_definition.configure_options:
        configure_options = ' '.join(
            self._project_definition.configure_options)

      if cflags and ldflags:
        command = (
            '{0:s} {1:s} ./configure --prefix={2:s} {3:s} '
            '--disable-dependency-tracking > {4:s} 2>&1').format(
                cflags, ldflags, prefix, configure_options, log_file_path)
      else:
        command = (
            './configure --prefix={0:s} {1:s} > {2:s} 2>&1').format(
                prefix, configure_options, log_file_path)

      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      command = 'make >> {0:s} 2>&1'.format(log_file_path)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      command = 'make install DESTDIR={0:s}/tmp >> {1:s} 2>&1'.format(
          os.path.abspath(source_directory), log_file_path)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      share_doc_path = os.path.join(
          source_directory, 'tmp', 'usr', 'local', 'share', 'doc',
          source_helper_object.project_name)
      if not os.path.exists(share_doc_path):
        os.makedirs(share_doc_path)

      for doc_filename in self._DOC_FILENAMES:
        doc_path = os.path.join(source_directory, doc_filename)
        if os.path.exists(doc_path):
          shutil.copy(doc_path, share_doc_path)

      licenses_directory = os.path.join(source_directory, 'licenses')
      if os.path.isdir(licenses_directory):
        filenames_glob = os.path.join(licenses_directory, '*')
        filenames = glob.glob(filenames_glob)

        for doc_path in filenames:
          shutil.copy(doc_path, share_doc_path)

      project_identifier = 'com.github.libyal.{0:s}'.format(
          source_helper_object.project_name)
      if not self._BuildPKG(
          source_directory, project_identifier, project_version, pkg_filename):
        return False

    if not self._BuildDmg(pkg_filename, dmg_filename):
      return False

    return True


class SetupPyPKGBuildHelper(PKGBuildHelper):
  """Helper to build MacOS-X packages (.pkg)."""

  def Build(self, source_helper_object):
    """Builds the pkg package and distributable disk image (.dmg).

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    project_version = source_helper_object.GetProjectVersion()

    logging.info('Building pkg of: {0:s}'.format(source_filename))

    if self._project_definition.patches:
      # TODO: add self._ApplyPatches
      pass

    dmg_filename = '{0:s}-{1!s}.dmg'.format(
        source_helper_object.project_name, project_version)
    pkg_filename = '{0:s}-{1!s}.pkg'.format(
        source_helper_object.project_name, project_version)
    log_file_path = os.path.join('..', self.LOG_FILENAME)

    if not os.path.exists(pkg_filename):
      command = 'python setup.py build > {0:s} 2>&1'.format(log_file_path)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      command = (
          'python setup.py install --root={0:s}/tmp '
          '--install-data=/usr/local > {1:s} 2>&1').format(
              os.path.abspath(source_directory), log_file_path)
      exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
          source_directory, command), shell=True)
      if exit_code != 0:
        logging.error('Running: "{0:s}" failed.'.format(command))
        return False

      # Copy the license file to the egg-info sub directory.
      for license_file in (
          'COPYING', 'LICENSE', 'LICENSE.TXT', 'LICENSE.txt'):
        if not os.path.exists(os.path.join(source_directory, license_file)):
          continue

        command = (
            'find ./tmp -type d -name \\*.egg-info -exec cp {0:s} {{}} '
            '\\;').format(license_file)
        exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
            source_directory, command), shell=True)
        if exit_code != 0:
          logging.error('Running: "{0:s}" failed.'.format(command))
          return False

      project_identifier = source_helper_object.GetProjectIdentifier()
      if not self._BuildPKG(
          source_directory, project_identifier, project_version, pkg_filename):
        return False

    if not self._BuildDmg(pkg_filename, dmg_filename):
      return False

    return True


class BaseRPMBuildHelper(BuildHelper):
  """Helper to build RPM packages (.rpm)."""

  _BUILD_DEPENDENCIES = frozenset([
      'git',
      'binutils',
      'autoconf',
      'automake',
      'libtool',
      'gettext-devel',
      'make',
      'pkgconf',
      'gcc',
      'gcc-c++',
      'flex',
      'byacc',
      'rpm-build',
      'python2-dateutil',
      'python2-devel',
      'python2-setuptools',
      'python2-test',
      'python3-dateutil',
      'python3-devel',
      'python3-setuptools',
      'python3-test',
  ])

  _BUILD_DEPENDENCY_PACKAGE_NAMES = {
      'bzip2': ['bzip2-devel'],
      'fuse': ['fuse-devel'],
      'libcrypto': ['openssl-devel'],
      'pytest-runner': [
          'python2-pytest-runner', 'python3-pytest-runner'],
      'sqlite': ['sqlite-devel'],
      'zeromq': ['libzmq3-devel'],
      'zlib': ['zlib-devel']
  }

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(BaseRPMBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    self.architecture = platform.machine()

    self.rpmbuild_path = os.path.join('~', 'rpmbuild')
    self.rpmbuild_path = os.path.expanduser(self.rpmbuild_path)

    self._rpmbuild_rpms_path = os.path.join(self.rpmbuild_path, 'RPMS')
    self._rpmbuild_sources_path = os.path.join(self.rpmbuild_path, 'SOURCES')
    self._rpmbuild_specs_path = os.path.join(self.rpmbuild_path, 'SPECS')
    self._rpmbuild_srpms_path = os.path.join(self.rpmbuild_path, 'SRPMS')

  def _BuildFromSpecFile(self, spec_filename, rpmbuild_flags='-ba'):
    """Builds the rpms directly from a spec file.

    Args:
      spec_filename (str): name of the spec file as stored in the rpmbuild
          SPECS sub directory.
      rpmbuild_flags (Optional(str)): rpmbuild flags.

    Returns:
      bool: True if successful, False otherwise.
    """
    spec_filename = os.path.join('SPECS', spec_filename)

    current_path = os.getcwd()
    os.chdir(self.rpmbuild_path)

    command = 'rpmbuild {0:s} {1:s} > {2:s} 2>&1'.format(
        rpmbuild_flags, spec_filename, self.LOG_FILENAME)
    exit_code = subprocess.call(command, shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))

    os.chdir(current_path)

    return exit_code == 0

  def _BuildFromSourcePackage(
      self, source_package_filename, rpmbuild_flags='-ta'):
    """Builds the rpms directly from the source package file.

    For this to work the source package needs to contain a valid rpm .spec file.

    Args:
      source_package_filename (str): name of the source package file.
      rpmbuild_flags (Optional(str)): rpmbuild flags.

    Returns:
      bool: True if successful, False otherwise.
    """
    command = 'rpmbuild {0:s} {1:s} > {2:s} 2>&1'.format(
        rpmbuild_flags, source_package_filename, self.LOG_FILENAME)
    exit_code = subprocess.call(command, shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def _CheckIsInstalled(self, package_name):
    """Checks if a package is installed.

    Args:
      package_name (str): name of the package.

    Returns:
      bool: True if the package is installed, False otherwise.
    """
    command = 'rpm -qi {0:s} >/dev/null 2>&1'.format(package_name)
    exit_code = subprocess.call(command, shell=True)
    return exit_code == 0

  def _CopySourcePackageToRPMBuildSources(self, source_package_filename):
    """Copies the source package to the rpmbuild SOURCES directory.

    Args:
      source_package_filename (str): name of the source package file.
    """
    rpm_source_package_path = os.path.join(
        self._rpmbuild_sources_path, source_package_filename)

    if not os.path.exists(rpm_source_package_path):
      self._CreateRPMbuildDirectories()

      shutil.copy(source_package_filename, rpm_source_package_path)

  def _CreateRPMbuildDirectories(self):
    """Creates the rpmbuild and sub directories."""
    if not os.path.exists(self.rpmbuild_path):
      os.mkdir(self.rpmbuild_path)

    if not os.path.exists(self._rpmbuild_sources_path):
      os.mkdir(self._rpmbuild_sources_path)

    if not os.path.exists(self._rpmbuild_specs_path):
      os.mkdir(self._rpmbuild_specs_path)

  def _CreateSpecFile(self, project_name, spec_file_data):
    """Creates a spec file in the rpmbuild directory.

    Args:
      project_name (str): name of the project.
      spec_file_data (str): spec file data.
    """
    spec_filename = os.path.join(
        self._rpmbuild_specs_path, '{0:s}.spec'.format(project_name))

    rpm_spec_file = open(spec_filename, 'w')
    rpm_spec_file.write(spec_file_data)
    rpm_spec_file.close()

  def _CopySourceFile(self, source_package_filename):
    """Copies the source file to the rpmbuild directory.

    Args:
      source_package_filename (str): name of the source package file.
    """
    shutil.copy(source_package_filename, self._rpmbuild_sources_path)

  def _GetFilenameSafeProjectInformation(self, source_helper_object):
    """Determines the filename safe project name and version.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      tuple: contains:

        * str: filename safe project name.
        * str: version.
    """
    project_name = source_helper_object.project_name
    if (self._project_definition.setup_name and
        project_name not in ('bencode', 'dateutil')):
      project_name = self._project_definition.setup_name

    project_version = source_helper_object.GetProjectVersion()
    if project_version and project_version.startswith('1!'):
      # Remove setuptools epoch.
      project_version = project_version[2:]

    if isinstance(project_version, py2to3.STRING_TYPES):
      project_version = project_version.replace('-', '_')

    return project_name, project_version

  def _GetSetupPySpecFilePath(self, source_helper_object, source_directory):
    """Retrieves the path of the setup.py generated .spec file.

    Args:
      source_helper_object (SourceHelper): source helper.
      source_directory (str): name of the source directory.

    Returns:
      str: path of the setup.py generated .spec file.
    """
    if self._project_definition.setup_name:
      setup_name = self._project_definition.setup_name
    else:
      setup_name = source_helper_object.project_name

    spec_filename = '{0:s}.spec'.format(setup_name)

    return os.path.join(source_directory, 'dist', spec_filename)

  def _MoveFilesToCurrentDirectory(self, filenames_glob):
    """Moves files into the current directory.

    Args:
      filenames_glob (str): glob of the filenames to move.
    """
    filenames = glob.glob(filenames_glob)
    for filename in filenames:
      logging.info('Moving: {0:s}'.format(filename))

      local_filename = os.path.basename(filename)
      if os.path.exists(local_filename):
        os.remove(local_filename)

      shutil.move(filename, '.')

  def CheckBuildDependencies(self):
    """Checks if the build dependencies are met.

    Returns:
      list[str]: build dependency names that are not met or an empty list.
    """
    missing_packages = []
    for package_name in self._BUILD_DEPENDENCIES:
      if not self._CheckIsInstalled(package_name):
        missing_packages.append(package_name)

    for package_name in self._project_definition.build_dependencies:
      dependencies = self._BUILD_DEPENDENCY_PACKAGE_NAMES.get(
          package_name, package_name)
      for dependency in dependencies:
        if not self._CheckIsInstalled(dependency):
          missing_packages.append(dependency)

    return missing_packages


class RPMBuildHelper(BaseRPMBuildHelper):
  """Helper to build RPM packages (.rpm)."""

  def _RemoveBuildDirectory(self, project_name, project_version):
    """Removes build directory.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filename = '{0:s}-{1!s}'.format(project_name, project_version)
    filename = os.path.join(self.rpmbuild_path, 'BUILD', filename)

    logging.info('Removing: {0:s}'.format(filename))

    try:
      shutil.rmtree(filename)
    except OSError:
      logging.warning('Unable to remove: {0:s}'.format(filename))

  def _RemoveOlderBuildDirectory(self, project_name, project_version):
    """Removes previous versions of build directories.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_to_ignore = '{0:s}-{1!s}'.format(
        project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    filenames_glob = os.path.join(
        self.rpmbuild_path, 'BUILD', '{0:s}-*'.format(project_name))
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        shutil.rmtree(filename)

  def _RemoveOlderRPMs(self, project_name, project_version):
    """Removes previous versions of .rpm files.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_to_ignore = '{0:s}-.*{1!s}-1.{2:s}.rpm'.format(
        project_name, project_version, self.architecture)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    rpm_filenames_glob = '{0:s}-*-1.{1:s}.rpm'.format(
        project_name, self.architecture)
    filenames = glob.glob(rpm_filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    filenames_glob = os.path.join(
        self.rpmbuild_path, 'RPMS', self.architecture, rpm_filenames_glob)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    rpm_filename = '{0:s}-{1!s}-1.{2:s}.rpm'.format(
        project_name, project_version, self.architecture)

    return not os.path.exists(rpm_filename)


class ConfigureMakeRPMBuildHelper(RPMBuildHelper):
  """Helper to build RPM packages (.rpm)."""

  def _MoveRPMs(self, project_name, project_version):
    """Moves the rpms from the rpmbuild directory into the current directory.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_glob = '{0:s}-*{1!s}-1.{2:s}.rpm'.format(
        project_name, project_version, self.architecture)
    filenames_glob = os.path.join(
        self._rpmbuild_rpms_path, self.architecture, filenames_glob)

    self._MoveFilesToCurrentDirectory(filenames_glob)

  def Build(self, source_helper_object):
    """Builds the rpms.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_package_filename = source_helper_object.Download()
    if not source_package_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    logging.info('Building rpm of: {0:s}'.format(source_package_filename))

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    # rpmbuild wants the source package filename without the status indication.
    rpm_source_package_filename = '{0:s}-{1!s}.tar.gz'.format(
        project_name, project_version)
    os.rename(source_package_filename, rpm_source_package_filename)

    build_successful = self._BuildFromSourcePackage(
        rpm_source_package_filename, rpmbuild_flags='-tb')

    if build_successful:
      self._MoveRPMs(project_name, project_version)
      self._RemoveBuildDirectory(project_name, project_version)

    # Change the source package filename back to the original.
    os.rename(rpm_source_package_filename, source_package_filename)

    return build_successful

  def Clean(self, source_helper_object):
    """Cleans the rpmbuild directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._RemoveOlderBuildDirectory(project_name, project_version)
    self._RemoveOlderRPMs(project_name, project_version)


class SetupPyRPMBuildHelper(RPMBuildHelper):
  """Helper to build RPM packages (.rpm)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(SetupPyRPMBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    if not project_definition.architecture_dependent:
      self.architecture = 'noarch'

  def _GenerateSpecFile(
      self, project_name, project_version, source_filename,
      source_helper_object):
    """Generates the rpm spec file.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
      source_filename (str): name of the source package file.
      source_helper_object (SourceHelper): source helper.

    Returns:
      str: path of the generated rpm spec file or None.
    """
    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return

    spec_file_generator = spec_file.RPMSpecFileGenerator(self._data_path)

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    if not spec_file_generator.GenerateWithSetupPy(
        source_directory, log_file_path):
      return

    if project_name.startswith('python-'):
      project_name = project_name[7:]

    input_file_path = self._GetSetupPySpecFilePath(
        source_helper_object, source_directory)

    spec_filename = '{0:s}.spec'.format(project_name)
    output_file_path = os.path.join(self._rpmbuild_specs_path, spec_filename)

    if not spec_file_generator.RewriteSetupPyGeneratedFile(
        self._project_definition, source_directory, source_filename,
        project_name, project_version, input_file_path, output_file_path):
      return

    return output_file_path

  def _MoveRPMs(self, project_name, project_version):
    """Moves the rpms from the rpmbuild directory into the current directory.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_glob = 'python*-{0:s}-*{1!s}-1.{2:s}.rpm'.format(
        project_name, project_version, self.architecture)
    filenames_glob = os.path.join(
        self._rpmbuild_rpms_path, self.architecture, filenames_glob)

    self._MoveFilesToCurrentDirectory(filenames_glob)

    filenames_glob = '{0:s}-*{1!s}-1.{2:s}.rpm'.format(
        project_name, project_version, self.architecture)
    filenames_glob = os.path.join(
        self._rpmbuild_rpms_path, self.architecture, filenames_glob)

    self._MoveFilesToCurrentDirectory(filenames_glob)

  def Build(self, source_helper_object):
    """Builds the rpms.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    logging.info('Building rpm of: {0:s}'.format(source_filename))

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._CopySourcePackageToRPMBuildSources(source_filename)

    rpm_spec_file_path = self._GenerateSpecFile(
        project_name, project_version, source_filename, source_helper_object)
    if not rpm_spec_file_path:
      logging.error('Unable to generate rpm spec file.')
      return False

    build_successful = self._BuildFromSpecFile(
        rpm_spec_file_path, rpmbuild_flags='-bb')

    if build_successful:
      self._MoveRPMs(project_name, project_version)
      self._RemoveBuildDirectory(project_name, project_version)

    return build_successful

  def Clean(self, source_helper_object):
    """Cleans the build and dist directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    # Remove previous versions build directories.
    for filename in ('build', 'dist'):
      if os.path.exists(filename):
        logging.info('Removing: {0:s}'.format(filename))
        shutil.rmtree(filename, True)

    # Remove previous versions of rpms.
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._RemoveOlderBuildDirectory(project_name, project_version)
    self._RemoveOlderRPMs(project_name, project_version)


class SRPMBuildHelper(BaseRPMBuildHelper):
  """Helper to build source RPM packages (.src.rpm)."""

  def _MoveRPMs(self, project_name, project_version):
    """Moves the rpms from the rpmbuild directory into the current directory.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_glob = '{0:s}-*{1!s}-1.src.rpm'.format(
        project_name, project_version)
    filenames_glob = os.path.join(self._rpmbuild_srpms_path, filenames_glob)

    self._MoveFilesToCurrentDirectory(filenames_glob)

  def _RemoveOlderSourceRPMs(self, project_name, project_version):
    """Removes previous versions of .src.rpm files.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
    """
    filenames_to_ignore = '{0:s}-.*{1!s}-1.src.rpm'.format(
        project_name, project_version)
    filenames_to_ignore = re.compile(filenames_to_ignore)

    src_rpm_filenames_glob = '{0:s}-*-1.src.rpm'.format(project_name)
    filenames = glob.glob(src_rpm_filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

    filenames_glob = os.path.join(
        self.rpmbuild_path, 'SRPMS', src_rpm_filenames_glob)
    filenames = glob.glob(filenames_glob)

    for filename in filenames:
      if not filenames_to_ignore.match(filename):
        logging.info('Removing: {0:s}'.format(filename))
        os.remove(filename)

  def CheckBuildRequired(self, source_helper_object):
    """Checks if a build is required.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if a build is required, False otherwise.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    srpm_filename = '{0:s}-{1!s}-1.src.rpm'.format(
        project_name, project_version)

    return not os.path.exists(srpm_filename)

  def Clean(self, source_helper_object):
    """Cleans the rpmbuild directory.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._RemoveOlderSourceRPMs(project_name, project_version)


class ConfigureMakeSRPMBuildHelper(SRPMBuildHelper):
  """Helper to build source RPM packages (.src.rpm)."""

  def Build(self, source_helper_object):
    """Builds the source rpm.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_package_filename = source_helper_object.Download()
    if not source_package_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    logging.info('Building source rpm of: {0:s}'.format(
        source_package_filename))

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    # rpmbuild wants the source package filename without the status indication.
    rpm_source_package_filename = '{0:s}-{1!s}.tar.gz'.format(
        project_name, project_version)
    os.rename(source_package_filename, rpm_source_package_filename)

    build_successful = self._BuildFromSourcePackage(
        rpm_source_package_filename, rpmbuild_flags='-ts')

    # TODO: test binary build of source package?

    if build_successful:
      self._MoveRPMs(project_name, project_version)

    # Change the source package filename back to the original.
    os.rename(rpm_source_package_filename, source_package_filename)

    return build_successful


class SetupPySRPMBuildHelper(SRPMBuildHelper):
  """Helper to build source RPM packages (.src.rpm)."""

  def __init__(self, project_definition, l2tdevtools_path):
    """Initializes a build helper.

    Args:
      project_definition (ProjectDefinition): project definition.
      l2tdevtools_path (str): path to the l2tdevtools directory.
    """
    super(SetupPySRPMBuildHelper, self).__init__(
        project_definition, l2tdevtools_path)
    if not project_definition.architecture_dependent:
      self.architecture = 'noarch'

  def _GenerateSpecFile(
      self, project_name, project_version, source_filename,
      source_helper_object):
    """Generates the rpm spec file.

    Args:
      project_name (str): name of the project.
      project_version (str): version of the project.
      source_filename (str): name of the source package file.
      source_helper_object (SourceHelper): source helper.

    Returns:
      str: path of the generated rpm spec file or None.
    """
    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return

    spec_file_generator = spec_file.RPMSpecFileGenerator(self._data_path)

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    if not spec_file_generator.GenerateWithSetupPy(
        source_directory, log_file_path):
      return

    if project_name.startswith('python-'):
      project_name = project_name[7:]

    input_file_path = self._GetSetupPySpecFilePath(
        source_helper_object, source_directory)

    spec_filename = '{0:s}.spec'.format(project_name)
    output_file_path = os.path.join(self._rpmbuild_specs_path, spec_filename)

    if not spec_file_generator.RewriteSetupPyGeneratedFile(
        self._project_definition, source_directory, source_filename,
        project_name, project_version, input_file_path, output_file_path):
      return

    return output_file_path

  def Build(self, source_helper_object):
    """Builds the source rpm.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    logging.info('Building source rpm of: {0:s}'.format(source_filename))

    project_name, project_version = self._GetFilenameSafeProjectInformation(
        source_helper_object)

    self._CopySourcePackageToRPMBuildSources(source_filename)

    rpm_spec_file_path = self._GenerateSpecFile(
        project_name, project_version, source_filename, source_helper_object)
    if not rpm_spec_file_path:
      logging.error('Unable to generate rpm spec file.')
      return False

    build_successful = self._BuildFromSpecFile(
        rpm_spec_file_path, rpmbuild_flags='-bs')

    # TODO: test binary build of source package?

    if build_successful:
      self._MoveRPMs(project_name, project_version)

    return build_successful


class SourceBuildHelper(BuildHelper):
  """Helper to build projects from source."""


class ConfigureMakeSourceBuildHelper(SourceBuildHelper):
  """Helper to build projects from source using configure and make."""

  def Build(self, source_helper_object):
    """Builds the source.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building source of: {0:s}'.format(source_filename))

    if self._project_definition.patches:
      # TODO: add self._ApplyPatches
      pass

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = './configure > {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    command = 'make >> {0:s} 2>&1'.format(log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True

  def Clean(self, unused_source_helper_object):
    """Cleans the source.

    Args:
      source_helper_object (SourceHelper): source helper.
    """
    # TODO: implement.
    return


class SetupPySourceBuildHelper(SourceBuildHelper):
  """Helper to build projects from source using setup.py."""

  def Build(self, source_helper_object):
    """Builds the source.

    Args:
      source_helper_object (SourceHelper): source helper.

    Returns:
      bool: True if successful, False otherwise.
    """
    source_filename = source_helper_object.Download()
    if not source_filename:
      logging.info('Download of: {0:s} failed'.format(
          source_helper_object.project_name))
      return False

    source_directory = source_helper_object.Create()
    if not source_directory:
      logging.error(
          'Extraction of source package: {0:s} failed'.format(source_filename))
      return False

    logging.info('Building source of: {0:s}'.format(source_filename))

    if self._project_definition.patches:
      # TODO: add self._ApplyPatches
      pass

    log_file_path = os.path.join('..', self.LOG_FILENAME)
    command = '{0:s} setup.py build > {1:s} 2>&1'.format(
        sys.executable, log_file_path)
    exit_code = subprocess.call('(cd {0:s} && {1:s})'.format(
        source_directory, command), shell=True)
    if exit_code != 0:
      logging.error('Running: "{0:s}" failed.'.format(command))
      return False

    return True


class BuildHelperFactory(object):
  """Factory class for build helpers."""

  _CONFIGURE_MAKE_BUILD_HELPER_CLASSES = {
      'dpkg': ConfigureMakeDPKGBuildHelper,
      'dpkg-source': ConfigureMakeSourceDPKGBuildHelper,
      'msi': ConfigureMakeMSIBuildHelper,
      'osc': ConfigureMakeOSCBuildHelper,
      'pkg': ConfigureMakePKGBuildHelper,
      'rpm': ConfigureMakeRPMBuildHelper,
      'source': ConfigureMakeSourceBuildHelper,
      'srpm': ConfigureMakeSRPMBuildHelper,
  }

  _SETUP_PY_BUILD_HELPER_CLASSES = {
      'dpkg': SetupPyDPKGBuildHelper,
      'dpkg-source': SetupPySourceDPKGBuildHelper,
      'msi': SetupPyMSIBuildHelper,
      'osc': SetupPyOSCBuildHelper,
      'pkg': SetupPyPKGBuildHelper,
      'rpm': SetupPyRPMBuildHelper,
      'source': SetupPySourceBuildHelper,
      'srpm': SetupPySRPMBuildHelper,
  }

  @classmethod
  def NewBuildHelper(cls, project_definition, build_target, l2tdevtools_path):
    """Creates a new build helper object.

    Args:
      project_definition (ProjectDefinition): project definition.
      build_target (str): build target.
      l2tdevtools_path (str): path to the l2tdevtools directory.

    Returns:
      BuildHelper: build helper or None.
    """
    if project_definition.build_system == 'configure_make':
      build_helper_class = cls._CONFIGURE_MAKE_BUILD_HELPER_CLASSES.get(
          build_target, None)

    elif project_definition.build_system == 'setup_py':
      build_helper_class = cls._SETUP_PY_BUILD_HELPER_CLASSES.get(
          build_target, None)

    else:
      build_helper_class = None

    if not build_helper_class:
      return

    return build_helper_class(project_definition, l2tdevtools_path)
